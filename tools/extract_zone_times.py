"""Extract zone timing statistics from production race data.

Compares observed cluster traversal times with current zone_metadata.toml
weights and suggests updates. For single-zone clusters, suggests zone-level
overrides. For multi-zone clusters, suggests cluster-level weight overrides
(bypassing the logarithmic aggregation formula entirely).

Usage:
    cd server && uv run python ../tools/extract_zone_times.py
    cd server && uv run python ../tools/extract_zone_times.py --deviation 40 --min-samples 8
    cd server && uv run python ../tools/extract_zone_times.py --report-only
    cd server && uv run python ../tools/extract_zone_times.py --since 2026-06-01 \\
        --types mini_dungeon legacy_dungeon --deviation 0 --min-samples 30
    cd server && uv run python ../tools/extract_zone_times.py --bands \\
        --since 2026-07-27 --bands-json /tmp/bands.json

``--bands`` reports the major and final boss arenas per scaling band (early,
mid, late: speedfog's ``weight_band``) and proposes ``weight = { early, mid,
late }`` tables, in real minutes, for zone_metadata.toml.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime
import json
import math
import statistics
import sys
from collections import defaultdict
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import asyncpg

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

DB_URL = "postgresql://speedfog:speedfog@localhost/speedfog_racing"
_SPEEDFOG_DATA = Path(__file__).resolve().parent.parent.parent / "speedfog" / "data"
ZONE_METADATA_PATH = _SPEEDFOG_DATA / "zone_metadata.toml"
CLUSTERS_JSON_PATH = _SPEEDFOG_DATA / "clusters.json"

# Scaling bands of a major boss arena's weight: speedfog's own definition.
sys.path.insert(0, str(_SPEEDFOG_DATA.parent))
from speedfog.boss_arena_constraints import (  # noqa: E402
    WEIGHT_BANDS,
    weight_band,
)

BANDED_TYPES = ("major_boss", "final_boss")
# A band measured on fewer clears takes the value of the nearest measured one.
BAND_MIN_SAMPLES = 20
# Clears a player needs before their speed is factored out of the estimate.
PLAYER_MIN_CLEARS = 5


def _round_half(value: float) -> float:
    """Round to the nearest 0.5 (e.g. 1.3 -> 1.5, 2.7 -> 2.5, 3.1 -> 3.0)."""
    return round(value * 2) / 2


def _floor_half(value: float) -> float:
    """Floor to the nearest 0.5 (e.g. 0.8 -> 0.5, 1.7 -> 1.5, 3.1 -> 3.0).

    Used for type defaults so the baseline represents the typical quick zone
    of that type, with overrides only for significantly slower zones.
    """
    return math.floor(value * 2) / 2


# ---------------------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------------------


async def load_seed_graphs(
    conn: asyncpg.Connection, since: datetime.date | None = None
) -> dict[str, dict]:
    """Load graph_json for all seeds used in races with zone_history data.

    ``since`` keeps only races created on or after that day.

    Returns: {seed_id: parsed_graph_json}
    """
    rows = await conn.fetch(
        """
        SELECT DISTINCT s.id, s.graph_json::text
        FROM seeds s
        JOIN races r ON r.seed_id = s.id
        JOIN participants p ON p.race_id = r.id
        WHERE p.zone_history IS NOT NULL
          AND p.zone_history::text NOT IN ('null', '[]')
          AND ($1::date IS NULL OR r.created_at >= $1::date)
          AND NOT r.race_items
        """,
        since,
    )
    graphs = {}
    for row in rows:
        graph_text = row["graph_json"]
        if graph_text:
            graphs[str(row["id"])] = json.loads(graph_text)
    return graphs


@dataclass
class ParticipantData:
    zone_history: list[dict]
    status: str
    igt_ms: int
    seed_id: str
    user_id: str = ""


async def load_participants(
    conn: asyncpg.Connection, since: datetime.date | None = None
) -> list[ParticipantData]:
    """Load participants with zone_history, status, igt_ms, and their seed_id.

    ``since`` keeps only races created on or after that day.
    """
    rows = await conn.fetch(
        """
        SELECT p.zone_history::text, p.status, p.igt_ms, r.seed_id::text,
               p.user_id::text
        FROM participants p
        JOIN races r ON p.race_id = r.id
        WHERE p.zone_history IS NOT NULL
          AND p.zone_history::text NOT IN ('null', '[]')
          AND ($1::date IS NULL OR r.created_at >= $1::date)
          AND NOT r.race_items
        """,
        since,
    )
    participants = []
    for row in rows:
        history = json.loads(row["zone_history"])
        if history:
            participants.append(
                ParticipantData(
                    zone_history=history,
                    status=row["status"],
                    igt_ms=row["igt_ms"],
                    seed_id=str(row["seed_id"]),
                    user_id=str(row["user_id"]),
                )
            )
    return participants


def load_zone_metadata(path: Path) -> dict:
    """Load current zone_metadata.toml."""
    if not path.exists():
        print(f"WARNING: {path} not found, using empty metadata", file=sys.stderr)
        return {"defaults": {}, "zones": {}, "clusters": {}}
    with open(path, "rb") as f:
        return tomllib.load(f)


def load_clusters_json(path: Path) -> dict[str, dict]:
    """Load current clusters.json as {cluster_id: cluster_data}.

    This is the source of truth for cluster composition (zones, type,
    weight, display_name). Historical graph_json in the DB may be stale.
    """
    if not path.exists():
        print(f"WARNING: {path} not found, cluster info will be empty", file=sys.stderr)
        return {}
    with open(path) as f:
        data = json.load(f)
    return {c["id"]: c for c in data["clusters"]}


# ---------------------------------------------------------------------------
# Computation
# ---------------------------------------------------------------------------


def _compute_outcome(
    current_layer: int,
    next_layer: int | None,
    is_last: bool,
    participant_status: str,
) -> str:
    """Determine zone outcome, mirroring web/src/lib/highlights.ts logic.

    Returns: "cleared", "backed", "playing", or "abandoned".
    """
    if not is_last and next_layer is not None:
        return "cleared" if next_layer > current_layer else "backed"
    if participant_status == "FINISHED":
        return "cleared"
    if participant_status == "PLAYING":
        return "playing"
    return "abandoned"


@dataclass(frozen=True)
class Clear:
    """One participant's cleared traversal of one node of their seed."""

    node_id: str
    minutes: float
    tier: int | None  # scaling tier of the node in that seed, None if absent
    user_id: str
    # The seed placed this (non final_boss) cluster as its final boss. Only
    # yielded on request: see ``iter_cluster_clears``.
    as_final: bool = False
    # The seed shuffled the boss of this arena: the time measures the drawn
    # boss. Major arenas with a shuffled boss are dropped before this point
    # unless they are the seed's final boss or of type final_boss.
    shuffled: bool = False


def iter_cluster_clears(
    participants: list[ParticipantData],
    seed_graphs: dict[str, dict],
    cluster_types: Mapping[str, str] | None = None,
    *,
    include_final: bool = False,
) -> Iterator[Clear]:
    """Yield cluster traversal durations in minutes, one per clear.

    For each participant, accumulates total time spent in each node across
    all visits (including re-traversals after deaths or backtracks), then
    produces one duration per participant per node. Only nodes where the
    player eventually progressed past (last visit outcome is "cleared")
    are included.

    This aggregation correctly accounts for deaths and roundtable detours:
    time before death + time on re-traversal = total effort to clear the
    cluster. Since there is one value per participant per cluster, the
    median across participants smooths out occasional double-traversals.

    Layers are resolved from the participant's own seed graph, since the
    same cluster can appear at different layers across different seeds.

    Durations are raw cluster traversal times (not decomposed per zone).

    ``cluster_types`` ({node_id: current cluster type}) drops the clears that
    do not measure the cluster in its own role: a seed that placed it as its
    final boss (nobody can turn back and the scaling is maxed out), and a
    major arena whose boss was shuffled (the time measures the drawn boss,
    not the arena). Minor arenas keep their shuffled clears: minor bosses
    are shuffled in most pools, so that is their usual traversal. Clears
    from before a cluster's type was reclassified are kept: the zones and
    the traversal are the same.

    ``include_final`` yields the clears of a cluster placed as the seed's
    final boss too, marked ``as_final``, instead of dropping them: the only
    data there is for a major boss the pools only ever use as a final boss.

    Prints the filter counts on stderr once exhausted.
    """
    skipped_backed = 0
    skipped_other = 0
    skipped_final = 0
    skipped_shuffled = 0

    for p in participants:
        history = p.zone_history
        seed_nodes = seed_graphs.get(p.seed_id, {}).get("nodes", {})

        # First pass: accumulate time per node across all visits.
        # Each entry's duration (until the next entry) is attributed to
        # the node the player was in at the time.
        node_total_ms: dict[str, float] = defaultdict(float)
        node_last_index: dict[str, int] = {}

        for i in range(len(history)):
            entry = history[i]
            node_id = entry["node_id"]
            is_last = i >= len(history) - 1

            if is_last:
                end_ms = p.igt_ms
            else:
                end_ms = history[i + 1]["igt_ms"]

            duration_ms = end_ms - entry["igt_ms"]
            if duration_ms > 0:
                node_total_ms[node_id] += duration_ms

            node_last_index[node_id] = i

        # Second pass: check outcome of each node's last visit.
        # Use layers from this participant's seed graph.
        for node_id, total_ms in node_total_ms.items():
            last_i = node_last_index[node_id]
            is_last = last_i >= len(history) - 1

            cur_layer = seed_nodes.get(node_id, {}).get("layer", 0)

            if not is_last:
                next_node_id = history[last_i + 1]["node_id"]
                next_layer: int | None = seed_nodes.get(next_node_id, {}).get(
                    "layer", 0
                )
            else:
                next_layer = None

            outcome = _compute_outcome(cur_layer, next_layer, is_last, p.status)

            if outcome == "backed":
                skipped_backed += 1
                continue
            if outcome in ("playing", "abandoned"):
                skipped_other += 1
                continue

            cluster_type = cluster_types.get(node_id) if cluster_types else None
            if cluster_type is not None:
                seed_node = seed_nodes.get(node_id, {})
                if (
                    seed_node.get("type") == "final_boss"
                    and cluster_type != "final_boss"
                ):
                    skipped_final += 1
                    if include_final:
                        yield Clear(
                            node_id=node_id,
                            minutes=total_ms / 1000.0 / 60.0,
                            tier=seed_node.get("tier"),
                            user_id=p.user_id,
                            as_final=True,
                            shuffled=bool(seed_node.get("randomized_bosses")),
                        )
                    continue
                if cluster_type == "major_boss" and seed_node.get("randomized_bosses"):
                    skipped_shuffled += 1
                    continue

            yield Clear(
                node_id=node_id,
                minutes=total_ms / 1000.0 / 60.0,
                tier=seed_nodes.get(node_id, {}).get("tier"),
                user_id=p.user_id,
                shuffled=bool(seed_nodes.get(node_id, {}).get("randomized_bosses"))
                and cluster_types is not None
                and cluster_types.get(node_id) in BANDED_TYPES,
            )

    print(
        f"  Filtered: {skipped_backed} backed, {skipped_other} playing/abandoned, "
        f"{skipped_final} final boss, {skipped_shuffled} shuffled major boss",
        file=sys.stderr,
    )


def compute_cluster_durations(
    participants: list[ParticipantData],
    seed_graphs: dict[str, dict],
    cluster_types: Mapping[str, str] | None = None,
) -> dict[str, list[float]]:
    """Cluster traversal durations in minutes (see ``iter_cluster_clears``).

    Returns: {node_id: [cluster_duration_minutes, ...]}
    """
    cluster_durations: dict[str, list[float]] = defaultdict(list)
    for clear in iter_cluster_clears(participants, seed_graphs, cluster_types):
        cluster_durations[clear.node_id].append(clear.minutes)
    return cluster_durations


@dataclass
class BandEstimate:
    """Per-band clear time of one major or final boss arena."""

    counts: dict[str, int]  # clears per band
    plain: dict[str, float]  # median minutes, measured bands only
    adjusted: dict[str, float]  # same, each player's speed factored out
    weights: dict[str, float] | None  # proposal for every band, None if no data
    from_final: bool = False  # measured on clears as a seed's final boss


def _fill_bands(measured: Mapping[str, float]) -> dict[str, float] | None:
    """Every band from the measured ones: a missing band takes the nearest
    measured band's value (the later one when two are equally near)."""
    if not measured:
        return None
    filled = {}
    for i, band in enumerate(WEIGHT_BANDS):
        nearest = min(
            (b for b in WEIGHT_BANDS if b in measured),
            key=lambda b: (abs(WEIGHT_BANDS.index(b) - i), -WEIGHT_BANDS.index(b)),
        )
        filled[band] = measured[nearest]
    return filled


def estimate_band_weights(
    clears: list[Clear],
    cluster_types: Mapping[str, str],
    *,
    min_samples: int = BAND_MIN_SAMPLES,
    adjust: bool = True,
) -> dict[str, BandEstimate]:
    """``{cluster id: BandEstimate}`` for the major and final boss arenas.

    A band's value is the median clear time of the arena at that band's
    tiers, in real minutes; a band with fewer than ``min_samples`` clears
    is not measured and takes the nearest measured band's value in
    ``weights``. Clears without a tier, and clears of an arena whose boss
    the seed shuffled, are ignored. Clears as a seed's final
    boss (``as_final``) only count for a cluster with no measured band
    otherwise: a major boss the pools never place mid-run.

    ``adjust`` factors each player's speed out before taking the proposal's
    median: fast players are over-represented on the hard, optional fights
    and at late tiers, which a plain median reads as a short fight. A
    player's factor is the median of ``log(minutes / cell median)`` over
    their clears in measured cells, for players with at least
    ``PLAYER_MIN_CLEARS`` of them; factors are centered on their
    clear-weighted median so the overall level stays that of the typical
    participant.
    """
    cells: dict[tuple[str, str], list[Clear]] = defaultdict(list)
    final_cells: dict[tuple[str, str], list[Clear]] = defaultdict(list)
    for clear in clears:
        if clear.shuffled:
            continue  # another boss stood in the arena
        if cluster_types.get(clear.node_id) in BANDED_TYPES and clear.tier is not None:
            target = final_cells if clear.as_final else cells
            target[(clear.node_id, weight_band(clear.tier))].append(clear)
    measured_nodes = {
        node_id for (node_id, _), group in cells.items() if len(group) >= min_samples
    }
    from_final = set()
    for (node_id, band), group in final_cells.items():
        if node_id not in measured_nodes:
            cells[(node_id, band)].extend(group)
            from_final.add(node_id)

    plain = {
        cell: statistics.median(c.minutes for c in group)
        for cell, group in cells.items()
        if len(group) >= min_samples
    }

    logs: dict[str, list[float]] = defaultdict(list)
    for cell, group in cells.items():
        if cell in plain:
            for c in group:
                logs[c.user_id].append(math.log(c.minutes / plain[cell]))
    factors = {
        user: statistics.median(values)
        for user, values in logs.items()
        if len(values) >= PLAYER_MIN_CLEARS
    }
    measured_clears = [c for cell in plain for c in cells[cell]]
    center = (
        statistics.median(factors.get(c.user_id, 0.0) for c in measured_clears)
        if measured_clears
        else 0.0
    )
    adjusted = {
        cell: statistics.median(
            c.minutes / math.exp(factors.get(c.user_id, center) - center)
            for c in cells[cell]
        )
        for cell in plain
    }

    estimates = {}
    for node_id in sorted({cell[0] for cell in cells}):
        chosen = adjusted if adjust else plain
        measured = {
            b: chosen[(node_id, b)] for b in WEIGHT_BANDS if (node_id, b) in chosen
        }
        filled = _fill_bands(measured)
        estimates[node_id] = BandEstimate(
            counts={b: len(cells.get((node_id, b), [])) for b in WEIGHT_BANDS},
            plain={
                b: plain[(node_id, b)] for b in WEIGHT_BANDS if (node_id, b) in plain
            },
            adjusted={
                b: adjusted[(node_id, b)]
                for b in WEIGHT_BANDS
                if (node_id, b) in adjusted
            },
            weights=(
                {b: max(0.01, round(v, 2)) for b, v in filled.items()}
                if filled is not None
                else None
            ),
            from_final=node_id in from_final,
        )
    return estimates


def current_band_weights(info: dict, metadata: dict, node_id: str) -> dict[str, float]:
    """The cluster's weight in each band today (a flat weight three times)."""
    bands = info.get("weights")
    if isinstance(bands, dict):
        return {b: float(bands[b]) for b in WEIGHT_BANDS}
    weight, _ = get_current_weight(node_id, info, metadata)
    return {b: float(weight) for b in WEIGHT_BANDS}


def format_band_report(
    estimates: Mapping[str, BandEstimate],
    cluster_info: dict[str, dict],
    current_metadata: dict,
) -> list[str]:
    """Per-band table of the major arenas, then the proposed TOML tables.

    A single-zone cluster is proposed under ``[zones.<zone>]``, unless it
    already carries a ``[clusters.<id>]`` weight (which wins); a multi-zone
    cluster under ``[clusters.<id>]``.
    """

    def cell(values: Mapping[str, float], band: str) -> str:
        return f"{values[band]:5.2f}" if band in values else "    -"

    lines = ["", "=" * 80, "MAJOR BOSS ARENAS PER SCALING BAND (minutes)", "=" * 80]
    lines.append(
        f"{'cluster':<34} {'current e/m/l':<17} {'plain e/m/l':<17} "
        f"{'adjusted e/m/l':<17} n e/m/l"
    )
    proposals: list[str] = []
    for node_id, est in estimates.items():
        info = cluster_info[node_id]
        current = current_band_weights(info, current_metadata, node_id)
        counts = "/".join(str(est.counts[b]) for b in WEIGHT_BANDS)
        lines.append(
            f"{node_id[:34]:<34} "
            f"{' '.join(cell(current, b) for b in WEIGHT_BANDS)} "
            f"{' '.join(cell(est.plain, b) for b in WEIGHT_BANDS)} "
            f"{' '.join(cell(est.adjusted, b) for b in WEIGHT_BANDS)} {counts}"
        )
        if est.weights is None:
            continue
        table = ", ".join(f"{b} = {est.weights[b]:g}" for b in WEIGHT_BANDS)
        in_clusters = node_id in current_metadata.get("clusters", {}) and (
            "weight" in current_metadata["clusters"][node_id]
        )
        if info["n_zones"] == 1 and not in_clusters:
            header = f"[zones.{info['primary_zone']}]"
        else:
            header = f"[clusters.{node_id}]"
        filled = [b for b in WEIGHT_BANDS if b not in est.adjusted]
        notes = []
        if filled:
            notes.append(f"{', '.join(filled)} from the nearest band")
        if est.from_final:
            notes.append("measured as a final boss")
        note = f"  # {'; '.join(notes)}" if notes else ""
        proposals.append(f"{header}  # {info['display_name']}")
        proposals.append(f"weight = {{ {table} }}{note}")
        proposals.append("")
    lines += ["", "=" * 80, "PROPOSED BAND TABLES (zone_metadata.toml)", "=" * 80, ""]
    lines += proposals
    return lines


def compute_duration_stats(durations: list[float]) -> dict:
    """Compute stats for a list of durations."""
    n = len(durations)
    if n == 0:
        return {"n": 0}
    return {
        "n": n,
        "avg": statistics.mean(durations),
        "median": statistics.median(durations),
        "min": min(durations),
        "max": max(durations),
        "std": statistics.stdev(durations) if n > 1 else 0.0,
    }


def build_cluster_info(clusters_json: dict[str, dict]) -> dict[str, dict]:
    """Build node_id -> cluster info from clusters.json (source of truth).

    Returns: {node_id: {type, zones, n_zones, primary_zone, weight, display_name}}
    """
    info: dict[str, dict] = {}
    for cluster_id, cdata in clusters_json.items():
        zones = cdata.get("zones", [])
        info[cluster_id] = {
            "type": cdata.get("type", "other"),
            "zones": zones,
            "n_zones": len(zones),
            "primary_zone": zones[0] if zones else cluster_id,
            "weight": cdata.get("weight"),
            "weights": cdata.get("weights"),
            "display_name": cdata.get("display_name", ""),
        }
    return info


def compute_type_defaults(
    cluster_durations: dict[str, list[float]],
    cluster_info: dict[str, dict],
) -> dict[str, dict]:
    """Compute new default weights per zone type from observed data.

    Only uses single-zone clusters for clean 1:1 mapping between
    cluster traversal time and zone weight (no inverse log needed).

    Returns: {type_name: {median, avg, n_zones, n_samples}}
    """
    # Single pass: collect per-cluster medians and sample counts by type
    type_medians: dict[str, list[float]] = defaultdict(list)
    type_samples: dict[str, int] = defaultdict(int)

    for node_id, durations in cluster_durations.items():
        info = cluster_info.get(node_id)
        if not info or info["n_zones"] != 1:
            continue
        type_medians[info["type"]].append(statistics.median(durations))
        type_samples[info["type"]] += len(durations)

    result = {}
    for type_name, cluster_medians in type_medians.items():
        med = _floor_half(statistics.median(cluster_medians))
        if med < 0.5:
            med = 0.5

        result[type_name] = {
            "median": med,
            "avg": round(statistics.mean(cluster_medians), 1),
            "n_zones": len(cluster_medians),
            "n_samples": type_samples[type_name],
        }

    return result


def get_current_weight(
    node_id: str,
    info: dict,
    metadata: dict,
) -> tuple[int | float, int | float | None]:
    """Get the current effective weight and explicit override for a cluster.

    A [clusters.*] weight override wins for any cluster, as in the generator.
    Otherwise single-zone: zone override from [zones.*] or type default;
    multi-zone: clusters.json weight.

    A per-band weight table (major boss arenas) reads as its mid value
    here; ``current_band_weights`` gives the three bands.

    Returns: (effective_weight, override_value_or_None)
    """

    def scalar(weight: Any) -> int | float:
        return weight["mid"] if isinstance(weight, dict) else weight

    clusters_meta = metadata.get("clusters", {})
    if node_id in clusters_meta:
        cm = clusters_meta[node_id]
        if isinstance(cm, dict) and "weight" in cm:
            return scalar(cm["weight"]), scalar(cm["weight"])

    if info["n_zones"] == 1:
        zone_name = info["primary_zone"]
        zones_meta = metadata.get("zones", {})
        if zone_name in zones_meta:
            zm = zones_meta[zone_name]
            if isinstance(zm, dict) and "weight" in zm:
                return scalar(zm["weight"]), scalar(zm["weight"])
            if isinstance(zm, int | float):
                return zm, zm
        defaults = metadata.get("defaults", {})
        return defaults.get(info["type"], 2), None

    w = info["weight"]
    return (w if w is not None else 2), None


# ---------------------------------------------------------------------------
# Report formatting
# ---------------------------------------------------------------------------


def _fmt_wt(w: int | float) -> str:
    """Format a weight value (int or float)."""
    if isinstance(w, float) and w != int(w):
        return f"{w:.1f}"
    return str(int(w))


def format_defaults_comparison(
    new_defaults: dict[str, dict],
    current_metadata: dict,
) -> list[str]:
    """Format comparison of current vs proposed type defaults."""
    lines = []
    lines.append("=" * 80)
    lines.append(
        "TYPE DEFAULTS (median of per-cluster medians, single-zone clusters only)"
    )
    lines.append("=" * 80)
    lines.append(
        f"  {'Type':<16} {'Current':>8} {'Proposed':>8} {'Avg':>6} "
        f"{'Zones':>6} {'Samples':>8}  {'Change'}"
    )
    lines.append("  " + "-" * 74)

    current_defaults = current_metadata.get("defaults", {})
    all_types = sorted(set(list(current_defaults.keys()) + list(new_defaults.keys())))

    for type_name in all_types:
        current = current_defaults.get(type_name, "?")
        new_data = new_defaults.get(type_name)
        if new_data:
            proposed = new_data["median"]
            avg = new_data["avg"]
            n_zones = new_data["n_zones"]
            n_samples = new_data["n_samples"]
            cur_val = current if isinstance(current, (int, float)) else None
            if cur_val is not None and cur_val != proposed:
                arrow = "<<" if proposed < cur_val else ">>"
                change = f"  {arrow} {_fmt_wt(cur_val)} -> {_fmt_wt(proposed)}"
            else:
                change = ""
            lines.append(
                f"  {type_name:<16} {str(current):>8} {_fmt_wt(proposed):>8} "
                f"{avg:>5.1f} {n_zones:>6} {n_samples:>8}{change}"
            )
        else:
            lines.append(f"  {type_name:<16} {str(current):>8} {'(no data)':>8}")

    return lines


def format_overrides(
    cluster_durations: dict[str, list[float]],
    cluster_info: dict[str, dict],
    current_metadata: dict,
    deviation_pct: float,
    min_samples: int,
) -> list[str]:
    """Format suggested overrides where observed median deviates from current weight.

    For single-zone clusters, suggests [zones.*] overrides, unless the
    cluster already carries a [clusters.*] weight (which wins).
    For multi-zone clusters, suggests [clusters.*] weight overrides.
    Proposals are rounded to 0.5 in both cases.
    """
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append(
        f"OVERRIDES (deviation > {deviation_pct:.0f}% from current weight, "
        f"N >= {min_samples})"
    )
    lines.append("=" * 80)

    current_defaults = current_metadata.get("defaults", {})
    clusters_meta = current_metadata.get("clusters", {})
    suggestions: list[dict] = []

    for node_id, durations in cluster_durations.items():
        n = len(durations)
        if n < min_samples:
            continue

        info = cluster_info.get(node_id)
        if not info:
            continue

        cluster_type = info["type"]
        n_zones = info["n_zones"]
        primary_zone = info["primary_zone"]
        median = statistics.median(durations)
        proposed = _round_half(median)
        if proposed < 0.5:
            proposed = 0.5

        effective_weight, current_override = get_current_weight(
            node_id, info, current_metadata
        )

        if effective_weight == 0:
            continue

        cluster_meta = clusters_meta.get(node_id)
        zone_level = n_zones == 1 and not (
            isinstance(cluster_meta, dict) and "weight" in cluster_meta
        )

        deviation = (
            abs(proposed - effective_weight) / ((proposed + effective_weight) / 2) * 100
        )
        cur_type_default = current_defaults.get(cluster_type, 2)

        suggestions.append(
            {
                "node_id": node_id,
                "primary_zone": primary_zone,
                "type": cluster_type,
                "n": n,
                "n_zones": n_zones,
                "zone_level": zone_level,
                "median": median,
                "proposed": proposed,
                "effective_weight": effective_weight,
                "deviation": deviation,
                "current_override": current_override,
                "cur_type_default": cur_type_default,
            }
        )

    suggestions.sort(key=lambda s: (-s["deviation"], s["node_id"]))

    lines.append(
        f"  {'Cluster':<36} {'Type':<14} {'N':>3} {'Zones':>5} {'Med':>6} "
        f"{'CurWt':>5} {'Prop':>5} {'Dev%':>5}  Action"
    )
    lines.append("  " + "-" * 96)

    n_changes = 0
    for s in suggestions:
        if s["deviation"] < deviation_pct:
            continue

        if s["proposed"] == s["effective_weight"]:
            continue

        # Determine action
        if s["zone_level"]:
            # Single-zone: suggest [zones.*] override
            if s["current_override"] is not None:
                if s["proposed"] == s["cur_type_default"]:
                    action = "REMOVE override (matches type default)"
                else:
                    action = (
                        f"UPDATE [zones] {_fmt_wt(s['current_override'])} "
                        f"-> {_fmt_wt(s['proposed'])}"
                    )
            else:
                action = (
                    f"ADD [zones.{s['primary_zone']}] weight = {_fmt_wt(s['proposed'])}"
                )
        else:
            # Multi-zone or cluster-level override: suggest [clusters.*] override
            if s["current_override"] is not None:
                action = (
                    f"UPDATE [clusters] {_fmt_wt(s['current_override'])} "
                    f"-> {_fmt_wt(s['proposed'])}"
                )
            else:
                action = (
                    f"ADD [clusters.{s['node_id']}] weight = {_fmt_wt(s['proposed'])}"
                )
        n_changes += 1

        clu_str = f"x{s['n_zones']}" if s["n_zones"] > 1 else ""
        lines.append(
            f"  {s['node_id']:<36} {s['type']:<14} {s['n']:>3} {clu_str:>5} "
            f"{s['median']:>5.1f}m {_fmt_wt(s['effective_weight']):>5} "
            f"{_fmt_wt(s['proposed']):>5} {s['deviation']:>4.0f}%  {action}"
        )

    lines.append(f"\n  {n_changes} change(s) suggested")

    return lines


def format_full_report(
    cluster_durations: dict[str, list[float]],
    cluster_info: dict[str, dict],
    current_metadata: dict,
) -> list[str]:
    """Format a full report of all cluster timing data."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("FULL CLUSTER TIMING DATA")
    lines.append("=" * 80)
    lines.append(
        f"  {'Cluster':<36} {'Type':<14} {'Zones':>5} {'N':>4} {'Avg':>6} "
        f"{'Med':>6} {'Min':>6} {'Max':>6} {'Std':>6} {'CurWt':>6}"
    )
    lines.append("  " + "-" * 104)

    rows = []
    for node_id, durations in cluster_durations.items():
        info = cluster_info.get(node_id)
        if not info:
            continue
        stats = compute_duration_stats(durations)
        current_wt, _ = get_current_weight(node_id, info, current_metadata)
        rows.append((node_id, info["type"], info["n_zones"], stats, current_wt))

    rows.sort(key=lambda r: (-r[3]["n"], r[0]))

    for node_id, cluster_type, n_zones, stats, current_wt in rows:
        n = stats["n"]
        if n == 0:
            continue
        clu_str = f"x{n_zones}" if n_zones > 1 else ""
        lines.append(
            f"  {node_id:<36} {cluster_type:<14} {clu_str:>5} {n:>4} "
            f"{stats['avg']:>5.1f}m {stats['median']:>5.1f}m "
            f"{stats['min']:>5.1f}m {stats['max']:>5.1f}m "
            f"{stats['std']:>5.1f}m {_fmt_wt(current_wt):>6}"
        )

    lines.append(f"\n  Total clusters: {len(rows)}")
    lines.append(f"  Total samples: {sum(r[3]['n'] for r in rows)}")

    return lines


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def main():
    parser = argparse.ArgumentParser(
        description="Extract zone timing stats and suggest zone_metadata.toml updates"
    )
    parser.add_argument(
        "--metadata",
        type=Path,
        default=ZONE_METADATA_PATH,
        help=f"Path to zone_metadata.toml (default: {ZONE_METADATA_PATH})",
    )
    parser.add_argument(
        "--clusters",
        type=Path,
        default=CLUSTERS_JSON_PATH,
        help=f"Path to clusters.json (default: {CLUSTERS_JSON_PATH})",
    )
    parser.add_argument(
        "--deviation",
        type=float,
        default=75,
        help="Min deviation %% from current weight to suggest override (default: 75)",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=5,
        help="Min samples to suggest a zone override (default: 5)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Only show full data report, skip change suggestions",
    )
    parser.add_argument(
        "--since",
        type=datetime.date.fromisoformat,
        help="Only use races created on or after this day (YYYY-MM-DD)",
    )
    parser.add_argument(
        "--types",
        nargs="+",
        metavar="TYPE",
        help="Only report clusters of these types (e.g. mini_dungeon legacy_dungeon)",
    )
    parser.add_argument(
        "--bands",
        action="store_true",
        help=(
            "Report the major and final boss arenas per scaling band and "
            "propose weight = { early, mid, late } tables, instead of the "
            "usual report"
        ),
    )
    parser.add_argument(
        "--bands-json",
        type=Path,
        help="With --bands: also write the proposals as {cluster_id: bands} JSON",
    )
    parser.add_argument(
        "--band-min-samples",
        type=int,
        default=BAND_MIN_SAMPLES,
        help=(
            "With --bands: clears a band needs to be measured "
            f"(default: {BAND_MIN_SAMPLES}); a thinner band takes the nearest one"
        ),
    )
    parser.add_argument(
        "--no-adjust",
        action="store_true",
        help="With --bands: propose plain medians, player speed not factored out",
    )
    parser.add_argument(
        "--db-url",
        default=DB_URL,
        help="PostgreSQL connection URL",
    )
    args = parser.parse_args()

    conn = await asyncpg.connect(args.db_url)
    try:
        print("Loading data...", file=sys.stderr)
        seed_graphs = await load_seed_graphs(conn, args.since)
        participants = await load_participants(conn, args.since)
        clusters_json = load_clusters_json(args.clusters)
        cluster_info = build_cluster_info(clusters_json)
        print(
            f"  {len(participants)} participants, "
            f"{len(seed_graphs)} seeds, {len(cluster_info)} current clusters",
            file=sys.stderr,
        )

        cluster_types = {nid: info["type"] for nid, info in cluster_info.items()}
        current_metadata = load_zone_metadata(args.metadata)

        if args.bands:
            if args.since is None:
                print(
                    "WARNING: --bands without --since: tiers above 21 were "
                    "clamped before 2026-07-27, older late clears were played "
                    "at a lower scaling than their tier says",
                    file=sys.stderr,
                )
            estimates = estimate_band_weights(
                list(
                    iter_cluster_clears(
                        participants, seed_graphs, cluster_types, include_final=True
                    )
                ),
                cluster_types,
                min_samples=args.band_min_samples,
                adjust=not args.no_adjust,
            )
            print(
                "\n".join(format_band_report(estimates, cluster_info, current_metadata))
            )
            if args.bands_json:
                args.bands_json.write_text(
                    json.dumps(
                        {
                            nid: {"weights": est.weights, "counts": est.counts}
                            for nid, est in estimates.items()
                            if est.weights is not None
                        },
                        indent=2,
                    ),
                    encoding="utf-8",
                )
            return

        all_cluster_durations = compute_cluster_durations(
            participants, seed_graphs, cluster_types
        )

        # Filter to current clusters only (ignore stale data from old seeds)
        cluster_durations = {
            nid: durs
            for nid, durs in all_cluster_durations.items()
            if nid in cluster_info
        }
        n_stale = len(all_cluster_durations) - len(cluster_durations)
        if n_stale:
            print(
                f"  Ignored {n_stale} stale cluster(s) not in clusters.json",
                file=sys.stderr,
            )
        if args.types:
            known_types = {info["type"] for info in cluster_info.values()}
            for unknown in sorted(set(args.types) - known_types):
                print(f"WARNING: no cluster has type {unknown!r}", file=sys.stderr)
            cluster_durations = {
                nid: durs
                for nid, durs in cluster_durations.items()
                if cluster_info[nid]["type"] in args.types
            }

        new_defaults = compute_type_defaults(cluster_durations, cluster_info)

        output: list[str] = []

        output.extend(format_defaults_comparison(new_defaults, current_metadata))

        if args.report_only:
            output.extend(
                format_full_report(cluster_durations, cluster_info, current_metadata)
            )
        else:
            output.extend(
                format_overrides(
                    cluster_durations,
                    cluster_info,
                    current_metadata,
                    args.deviation,
                    args.min_samples,
                )
            )
            output.extend(
                format_full_report(cluster_durations, cluster_info, current_metadata)
            )

        print("\n".join(output))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
