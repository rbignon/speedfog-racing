"""Extract zone timing statistics from production race data.

Compares observed cluster traversal times with current zone_metadata.toml
weights and suggests updates. For single-zone clusters, suggests zone-level
overrides. For multi-zone clusters, suggests cluster-level weight overrides
(bypassing the logarithmic aggregation formula entirely).

Usage:
    cd server && uv run python ../tools/extract_zone_times.py
    cd server && uv run python ../tools/extract_zone_times.py --deviation 40 --min-samples 8
    cd server && uv run python ../tools/extract_zone_times.py --report-only
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

import asyncpg

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

DB_URL = "postgresql://speedfog:speedfog@localhost/speedfog_racing"
_SPEEDFOG_DATA = Path(__file__).resolve().parent.parent.parent / "speedfog" / "data"
ZONE_METADATA_PATH = _SPEEDFOG_DATA / "zone_metadata.toml"
CLUSTERS_JSON_PATH = _SPEEDFOG_DATA / "clusters.json"


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


async def load_seed_graphs(conn: asyncpg.Connection) -> dict[str, dict]:
    """Load graph_json for all seeds used in races with zone_history data.

    Returns: {seed_id: parsed_graph_json}
    """
    rows = await conn.fetch("""
        SELECT DISTINCT s.id, s.graph_json::text
        FROM seeds s
        JOIN races r ON r.seed_id = s.id
        JOIN participants p ON p.race_id = r.id
        WHERE p.zone_history IS NOT NULL
          AND p.zone_history::text NOT IN ('null', '[]')
    """)
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


async def load_participants(conn: asyncpg.Connection) -> list[ParticipantData]:
    """Load participants with zone_history, status, igt_ms, and their seed_id."""
    rows = await conn.fetch("""
        SELECT p.zone_history::text, p.status, p.igt_ms, r.seed_id::text
        FROM participants p
        JOIN races r ON p.race_id = r.id
        WHERE p.zone_history IS NOT NULL
          AND p.zone_history::text NOT IN ('null', '[]')
    """)
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


def compute_cluster_durations(
    participants: list[ParticipantData],
    seed_graphs: dict[str, dict],
) -> dict[str, list[float]]:
    """Compute cluster traversal durations in minutes.

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

    Returns: {node_id: [cluster_duration_minutes, ...]}
    """
    cluster_durations: dict[str, list[float]] = defaultdict(list)
    skipped_backed = 0
    skipped_other = 0

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

            cluster_durations[node_id].append(total_ms / 1000.0 / 60.0)

    print(
        f"  Filtered: {skipped_backed} backed, {skipped_other} playing/abandoned",
        file=sys.stderr,
    )

    return cluster_durations


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

    Single-zone: zone override from [zones.*] or type default.
    Multi-zone: cluster override from [clusters.*] or clusters.json weight.

    Returns: (effective_weight, override_value_or_None)
    """
    if info["n_zones"] == 1:
        zone_name = info["primary_zone"]
        zones_meta = metadata.get("zones", {})
        if zone_name in zones_meta:
            zm = zones_meta[zone_name]
            if isinstance(zm, dict) and "weight" in zm:
                return zm["weight"], zm["weight"]
            if isinstance(zm, int | float):
                return zm, zm
        defaults = metadata.get("defaults", {})
        return defaults.get(info["type"], 2), None

    # Multi-zone: cluster override in TOML takes precedence, then clusters.json weight
    clusters_meta = metadata.get("clusters", {})
    if node_id in clusters_meta:
        cm = clusters_meta[node_id]
        if isinstance(cm, dict) and "weight" in cm:
            return cm["weight"], cm["weight"]
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

    For single-zone clusters, suggests [zones.*] overrides.
    For multi-zone clusters, suggests [clusters.*] weight overrides.
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

        # For multi-zone clusters, round proposed to int (cluster weights are ints)
        if n_zones > 1:
            proposed = round(proposed)
            if proposed < 1:
                proposed = 1

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
        if s["n_zones"] == 1:
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
            # Multi-zone: suggest [clusters.*] override
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
        "--db-url",
        default=DB_URL,
        help="PostgreSQL connection URL",
    )
    args = parser.parse_args()

    conn = await asyncpg.connect(args.db_url)
    try:
        print("Loading data...", file=sys.stderr)
        seed_graphs = await load_seed_graphs(conn)
        participants = await load_participants(conn)
        clusters_json = load_clusters_json(args.clusters)
        cluster_info = build_cluster_info(clusters_json)
        print(
            f"  {len(participants)} participants, "
            f"{len(seed_graphs)} seeds, {len(cluster_info)} current clusters",
            file=sys.stderr,
        )

        all_cluster_durations = compute_cluster_durations(participants, seed_graphs)
        current_metadata = load_zone_metadata(args.metadata)

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
