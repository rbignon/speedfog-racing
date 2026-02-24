"""Extract zone timing statistics from production race data.

Compares observed cluster traversal times with current zone_metadata.toml
weights and suggests updates to defaults and zone-specific overrides.

For multi-zone clusters, applies the inverse of the logarithmic aggregation
formula to back-calculate estimated per-zone weights:
    avg_zone_weight = cluster_time / (1 + 0.5 * ln(n_zones))

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
ZONE_METADATA_PATH = (
    Path(__file__).resolve().parent.parent.parent
    / "speedfog"
    / "data"
    / "zone_metadata.toml"
)


def _log_factor(n_zones: int) -> float:
    """Logarithmic aggregation factor from generate_clusters.py.

    cluster_weight = avg_zone_weight * (1 + 0.5 * ln(n_zones))
    """
    return 1 + 0.5 * math.log(n_zones) if n_zones > 1 else 1.0


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


def build_node_mapping(seed_graphs: dict[str, dict]) -> dict[str, dict]:
    """Build node_id -> {zones, type, weight, layer} from all seed graphs."""
    mapping: dict[str, dict] = {}
    for graph in seed_graphs.values():
        nodes = graph.get("nodes", {})
        for node_id, node_data in nodes.items():
            if node_id not in mapping:
                mapping[node_id] = {
                    "zones": node_data.get("zones", []),
                    "type": node_data.get("type", "other"),
                    "weight": node_data.get("weight"),
                    "display_name": node_data.get("display_name", ""),
                    "layer": node_data.get("layer", 0),
                }
    return mapping


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
        return {"defaults": {}, "zones": {}}
    with open(path, "rb") as f:
        return tomllib.load(f)


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


def compute_zone_durations(
    participants: list[ParticipantData],
    node_mapping: dict[str, dict],
) -> dict[str, list[float]]:
    """Compute estimated per-zone durations in minutes, excluding backtracks.

    Only includes zones with outcome "cleared" (player progressed past them).
    Backtracks, abandoned zones, and zones still being played are excluded.

    For multi-zone clusters, applies the inverse log formula to estimate
    the average per-zone weight:
        zone_weight = cluster_time / (1 + 0.5 * ln(n_zones))

    For the last zone of a finished participant, uses participant.igt_ms
    as the end time (since there's no next zone_history entry).

    Returns: {primary_zone: [estimated_zone_duration_minutes, ...]}
    """
    zone_durations: dict[str, list[float]] = defaultdict(list)
    skipped_backed = 0
    skipped_other = 0

    for p in participants:
        history = p.zone_history
        for i in range(len(history)):
            entry = history[i]
            node_id = entry["node_id"]
            is_last = i >= len(history) - 1

            # Determine end time
            if is_last:
                end_ms = p.igt_ms
            else:
                end_ms = history[i + 1]["igt_ms"]

            duration_ms = end_ms - entry["igt_ms"]
            if duration_ms <= 0:
                continue

            # Determine outcome using layer comparison
            cur_info = node_mapping.get(node_id)
            cur_layer = cur_info["layer"] if cur_info else 0

            if not is_last:
                next_node_id = history[i + 1]["node_id"]
                next_info = node_mapping.get(next_node_id)
                next_layer: int | None = next_info["layer"] if next_info else 0
            else:
                next_layer = None

            outcome = _compute_outcome(cur_layer, next_layer, is_last, p.status)

            if outcome == "backed":
                skipped_backed += 1
                continue
            if outcome in ("playing", "abandoned"):
                skipped_other += 1
                continue

            # Only "cleared" zones reach here
            cluster_time_min = duration_ms / 1000.0 / 60.0

            if cur_info and cur_info["zones"]:
                primary_zone = cur_info["zones"][0]
                n_zones = len(cur_info["zones"])
                zone_time_min = cluster_time_min / _log_factor(n_zones)
                zone_durations[primary_zone].append(zone_time_min)
            else:
                zone_name = node_id.rsplit("_", 1)[0] if len(node_id) > 5 else node_id
                zone_durations[zone_name].append(cluster_time_min)

    print(
        f"  Filtered: {skipped_backed} backed, {skipped_other} playing/abandoned",
        file=sys.stderr,
    )

    return zone_durations


def compute_zone_stats(durations: list[float]) -> dict:
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


def build_zone_type_map(node_mapping: dict[str, dict]) -> dict[str, str]:
    """Build primary_zone -> cluster_type mapping."""
    zone_types: dict[str, str] = {}
    for node_info in node_mapping.values():
        zones = node_info["zones"]
        if zones:
            primary = zones[0]
            if primary not in zone_types:
                zone_types[primary] = node_info["type"]
    return zone_types


def build_zone_cluster_size(node_mapping: dict[str, dict]) -> dict[str, int]:
    """Build primary_zone -> cluster_size (number of zones in the cluster)."""
    sizes: dict[str, int] = {}
    for node_info in node_mapping.values():
        zones = node_info["zones"]
        if zones:
            primary = zones[0]
            if primary not in sizes:
                sizes[primary] = len(zones)
    return sizes


def compute_type_defaults(
    zone_durations: dict[str, list[float]],
    zone_types: dict[str, str],
    cluster_sizes: dict[str, int],
) -> dict[str, dict]:
    """Compute new default weights per zone type from observed data.

    Only uses single-zone clusters for clean 1:1 mapping between
    cluster traversal time and zone weight (no inverse log needed).

    Returns: {type_name: {median, avg, n_zones, n_samples}}
    """
    type_durations: dict[str, list[float]] = defaultdict(list)

    for zone_name, durations in zone_durations.items():
        zone_type = zone_types.get(zone_name)
        if not zone_type:
            continue
        if cluster_sizes.get(zone_name, 1) == 1:
            type_durations[zone_type].extend(durations)

    result = {}
    for type_name, all_durations in type_durations.items():
        if not all_durations:
            continue
        # Median of per-zone medians (avoids high-sample zones dominating)
        zone_medians = []
        for zone_name, durations in zone_durations.items():
            if (
                zone_types.get(zone_name) == type_name
                and cluster_sizes.get(zone_name, 1) == 1
            ):
                zone_medians.append(statistics.median(durations))

        med = _floor_half(statistics.median(zone_medians))
        if med < 0.5:
            med = 0.5

        result[type_name] = {
            "median": med,
            "avg": round(statistics.mean(zone_medians), 1),
            "n_zones": len(zone_medians),
            "n_samples": len(all_durations),
        }

    return result


def get_current_weight(zone_name: str, zone_type: str, metadata: dict) -> int | float:
    """Get the current weight from zone_metadata.toml."""
    zones_meta = metadata.get("zones", {})
    if zone_name in zones_meta:
        zm = zones_meta[zone_name]
        if isinstance(zm, dict) and "weight" in zm:
            return zm["weight"]
    defaults = metadata.get("defaults", {})
    return defaults.get(zone_type, 2)


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
        "TYPE DEFAULTS (median of per-zone medians, single-zone clusters only)"
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


def format_zone_overrides(
    zone_durations: dict[str, list[float]],
    zone_types: dict[str, str],
    cluster_sizes: dict[str, int],
    new_defaults: dict[str, dict],
    current_metadata: dict,
    deviation_pct: float,
    min_samples: int,
) -> list[str]:
    """Format suggested zone overrides where median deviates from type default."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append(
        f"ZONE OVERRIDES (deviation > {deviation_pct:.0f}% from new type default, "
        f"N >= {min_samples})"
    )
    lines.append("=" * 80)

    zones_meta = current_metadata.get("zones", {})
    suggestions: list[dict] = []

    for zone_name, durations in zone_durations.items():
        n = len(durations)
        if n < min_samples:
            continue

        zone_type = zone_types.get(zone_name, "other")
        type_default = new_defaults.get(zone_type, {}).get("median")
        if type_default is None or type_default == 0:
            continue

        median = statistics.median(durations)
        n_zones = cluster_sizes.get(zone_name, 1)
        proposed = _round_half(median)
        if proposed < 0.5:
            proposed = 0.5

        deviation = abs(proposed - type_default) / type_default * 100

        # Get current override (if any)
        current_override = None
        if zone_name in zones_meta:
            zm = zones_meta[zone_name]
            if isinstance(zm, dict) and "weight" in zm:
                current_override = zm["weight"]

        suggestions.append(
            {
                "zone": zone_name,
                "type": zone_type,
                "n": n,
                "n_zones": n_zones,
                "median": median,
                "proposed": proposed,
                "type_default": type_default,
                "deviation": deviation,
                "current_override": current_override,
            }
        )

    suggestions.sort(key=lambda s: (-s["deviation"], s["zone"]))

    lines.append(
        f"  {'Zone':<36} {'Type':<14} {'N':>3} {'Clu':>3} {'Med':>6} "
        f"{'TyDef':>5} {'Prop':>5} {'Dev%':>5} {'CurOv':>5}  Action"
    )
    lines.append("  " + "-" * 100)

    n_changes = 0
    for s in suggestions:
        needs_override = s["deviation"] >= deviation_pct
        already_correct = s["current_override"] == s["proposed"]
        already_default = s["proposed"] == s["type_default"]

        if already_default:
            if s["current_override"] is not None:
                action = "REMOVE override (matches default)"
                n_changes += 1
            else:
                continue
        elif needs_override:
            if already_correct:
                action = "(already correct)"
            elif s["current_override"] is not None:
                action = (
                    f"UPDATE {_fmt_wt(s['current_override'])} "
                    f"-> {_fmt_wt(s['proposed'])}"
                )
                n_changes += 1
            else:
                action = f"ADD weight = {_fmt_wt(s['proposed'])}"
                n_changes += 1
        else:
            continue

        cur_str = (
            _fmt_wt(s["current_override"]) if s["current_override"] is not None else "-"
        )
        clu_str = f"x{s['n_zones']}" if s["n_zones"] > 1 else ""
        lines.append(
            f"  {s['zone']:<36} {s['type']:<14} {s['n']:>3} {clu_str:>3} "
            f"{s['median']:>5.1f}m {_fmt_wt(s['type_default']):>5} "
            f"{_fmt_wt(s['proposed']):>5} {s['deviation']:>4.0f}% "
            f"{cur_str:>5}  {action}"
        )

    lines.append(f"\n  {n_changes} change(s) suggested")

    return lines


def format_full_report(
    zone_durations: dict[str, list[float]],
    zone_types: dict[str, str],
    cluster_sizes: dict[str, int],
    current_metadata: dict,
) -> list[str]:
    """Format a full report of all zone timing data."""
    lines = []
    lines.append("")
    lines.append("=" * 80)
    lines.append("FULL ZONE TIMING DATA (durations adjusted for cluster size)")
    lines.append("=" * 80)
    lines.append(
        f"  {'Zone':<36} {'Type':<14} {'Clu':>3} {'N':>4} {'Avg':>6} "
        f"{'Med':>6} {'Min':>6} {'Max':>6} {'Std':>6} {'CurWt':>6}"
    )
    lines.append("  " + "-" * 104)

    rows = []
    for zone_name, durations in zone_durations.items():
        stats = compute_zone_stats(durations)
        zone_type = zone_types.get(zone_name, "?")
        current_wt = get_current_weight(zone_name, zone_type, current_metadata)
        n_zones = cluster_sizes.get(zone_name, 1)
        rows.append((zone_name, zone_type, n_zones, stats, current_wt))

    rows.sort(key=lambda r: (-r[3]["n"], r[0]))

    for zone_name, zone_type, n_zones, stats, current_wt in rows:
        n = stats["n"]
        if n == 0:
            continue
        clu_str = f"x{n_zones}" if n_zones > 1 else ""
        lines.append(
            f"  {zone_name:<36} {zone_type:<14} {clu_str:>3} {n:>4} "
            f"{stats['avg']:>5.1f}m {stats['median']:>5.1f}m "
            f"{stats['min']:>5.1f}m {stats['max']:>5.1f}m "
            f"{stats['std']:>5.1f}m {_fmt_wt(current_wt):>6}"
        )

    lines.append(f"\n  Total zones: {len(rows)}")
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
        "--deviation",
        type=float,
        default=100,
        help="Min deviation %% from type default to suggest override (default: 100)",
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
        node_mapping = build_node_mapping(seed_graphs)
        participants = await load_participants(conn)
        print(
            f"  {len(node_mapping)} nodes, {len(participants)} participants, "
            f"{len(seed_graphs)} seeds",
            file=sys.stderr,
        )

        zone_durations = compute_zone_durations(participants, node_mapping)
        zone_types = build_zone_type_map(node_mapping)
        cluster_sizes = build_zone_cluster_size(node_mapping)
        current_metadata = load_zone_metadata(args.metadata)

        new_defaults = compute_type_defaults(zone_durations, zone_types, cluster_sizes)

        output: list[str] = []

        output.extend(format_defaults_comparison(new_defaults, current_metadata))

        if args.report_only:
            output.extend(
                format_full_report(
                    zone_durations, zone_types, cluster_sizes, current_metadata
                )
            )
        else:
            output.extend(
                format_zone_overrides(
                    zone_durations,
                    zone_types,
                    cluster_sizes,
                    new_defaults,
                    current_metadata,
                    args.deviation,
                    args.min_samples,
                )
            )
            output.extend(
                format_full_report(
                    zone_durations, zone_types, cluster_sizes, current_metadata
                )
            )

        print("\n".join(output))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
