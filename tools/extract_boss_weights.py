"""Suggest boss.weight values for speedfog's data/boss_arena_tags.json.

A boss node's clear time mixes the arena (approach, exit), the boss fight,
the scaling tier, the player and the pool's power curve. Boss randomization
decorrelates bosses from arenas, so a robust additive fit of the log clear
time (arena + boss + tier + user + pool, multi-factor median polish)
isolates the boss. Each factor is centered on its observation-weighted
median, so a weight is the median node time for that boss under typical
arena, tier, player and pool: comparable across bosses, indicative in
absolute terms. Clears follow tools/extract_zone_times.py (time summed over
every visit, kept when the last visit cleared the node). Bosses are
attributed from the seed's enemy_assignments, else from a randomized_bosses
name matching a single entity; multi-slot nodes are skipped. Small samples
are shrunk toward the pool median (empirical Bayes).

Usage:
    cd server && uv run python ../tools/extract_boss_weights.py
    cd server && uv run python ../tools/extract_boss_weights.py --write
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import statistics
import sys
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import asyncpg
from extract_zone_times import DB_URL, _SPEEDFOG_DATA, _compute_outcome

sys.path.insert(0, str(_SPEEDFOG_DATA.parent))
from speedfog.boss_arena_constraints import load_tags  # noqa: E402
from speedfog.clusters import load_clusters  # noqa: E402
from speedfog.enemy_data import (  # noqa: E402
    parse_boss_extra_names,
    parse_boss_key_names,
    parse_boss_phases,
    resolve_entity_id,
)
from speedfog.item_randomizer import _compose_pool  # noqa: E402

TAGS_PATH = _SPEEDFOG_DATA / "boss_arena_tags.json"
ENEMY_TXT_PATH = _SPEEDFOG_DATA / "enemy.txt"
CLUSTERS_PATH = _SPEEDFOG_DATA / "clusters.json"

# Node type -> speedfog pool kind. final_boss nodes are single-node layers,
# too few to calibrate; their bosses are measured as randomized majors.
BOSS_JOBS = {"boss_arena": "minor", "major_boss": "major"}
FACTORS = ("arena", "boss", "tier", "user", "pool")
# Tiers above this are rare; pooling them keeps their factor estimable.
TIER_CAP = 24


@dataclass(frozen=True)
class BossClear:
    node_id: str
    minutes: float


def boss_clears(
    history: Sequence[Mapping[str, Any]],
    igt_ms: int,
    status: str,
    nodes: Mapping[str, Mapping[str, Any]],
) -> list[BossClear]:
    """Cleared boss nodes of one participant, with their total time.

    Time is summed over every visit (deaths and runbacks included); a node
    counts only when its last visit cleared it (``_compute_outcome``).
    """
    total_ms: dict[str, float] = defaultdict(float)
    last_index: dict[str, int] = {}
    for i, entry in enumerate(history):
        end_ms = igt_ms if i == len(history) - 1 else history[i + 1]["igt_ms"]
        if end_ms - entry["igt_ms"] > 0:
            total_ms[entry["node_id"]] += end_ms - entry["igt_ms"]
        last_index[entry["node_id"]] = i
    clears = []
    for node_id, ms in total_ms.items():
        node = nodes.get(node_id)
        if node is None or node.get("type") not in BOSS_JOBS:
            continue
        i = last_index[node_id]
        is_last = i == len(history) - 1
        next_layer = None
        if not is_last:
            next_layer = nodes.get(history[i + 1]["node_id"], {}).get("layer", 0)
        outcome = _compute_outcome(node.get("layer", 0), next_layer, is_last, status)
        if outcome == "cleared":
            clears.append(BossClear(node_id, ms / 60000.0))
    return clears


def name_index(
    tags: Mapping[int, Any],
    key_names: Mapping[int, str],
    extra_names: Mapping[int, str],
) -> dict[str, set[int]]:
    """Every display name a seed may carry -> the entities it can denote."""
    index: dict[str, set[int]] = defaultdict(set)
    for eid, entry in tags.items():
        for name in (key_names.get(eid), extra_names.get(eid), entry.name):
            if name:
                index[name].add(eid)
    return dict(index)


def attribute(
    node: Mapping[str, Any],
    enemy_assignments: Mapping[str, str] | None,
    names: Mapping[str, set[int]],
    phases: Mapping[int, int],
) -> int | None:
    """Boss entity fought in a single-slot boss node, or None when unknown."""
    if not node.get("defeat_flag"):
        return None
    leader = resolve_entity_id(node["defeat_flag"])
    if leader in phases:
        return None
    if enemy_assignments is not None:
        boss = enemy_assignments.get(str(leader))
        return int(boss) if boss else None
    bosses = node.get("randomized_bosses") or []
    if len(bosses) != 1:
        return None
    candidates = names.get(bosses[0], set())
    return next(iter(candidates)) if len(candidates) == 1 else None


def fit_effects(
    rows: Sequence[Mapping[str, Any]],
    factors: Sequence[str] = FACTORS,
    max_iter: int = 20,
    tol: float = 1e-3,
) -> tuple[float, dict[str, dict[Any, float]]]:
    """Multi-factor median polish of ``row["y"]`` over ``factors``.

    Returns ``(mu, effects)``; each factor's effects are centered so that
    their median over the rows is 0.
    """
    mu = statistics.median(r["y"] for r in rows)
    effects: dict[str, dict[Any, float]] = {f: defaultdict(float) for f in factors}
    for _ in range(max_iter):
        delta = 0.0
        for f in factors:
            residuals: dict[Any, list[float]] = defaultdict(list)
            for r in rows:
                others = sum(effects[g][r[g]] for g in factors if g != f)
                residuals[r[f]].append(r["y"] - mu - others)
            for level, values in residuals.items():
                new = statistics.median(values)
                delta = max(delta, abs(new - effects[f][level]))
                effects[f][level] = new
            center = statistics.median(effects[f][r[f]] for r in rows)
            for level in effects[f]:
                effects[f][level] -= center
            mu += center
        if delta < tol:
            break
    return mu, {f: dict(e) for f, e in effects.items()}


def shrunk_weights(
    rows: Sequence[Mapping[str, Any]],
    mu: float,
    effects: Mapping[str, Mapping[Any, float]],
    pool: Iterable[Any],
) -> dict[Any, tuple[float, int]]:
    """``{boss: (minutes, n)}`` for the pool bosses seen in ``rows``.

    Boss effects are shrunk toward the pool median by ``n / (n + k)``, with
    ``k = sigma^2 / tau^2`` (per-observation residual variance over the
    between-boss variance, both robust).
    """
    residuals = [r["y"] - mu - sum(effects[f][r[f]] for f in effects) for r in rows]
    mid = statistics.median(residuals)
    sigma2 = (1.4826 * statistics.median(abs(x - mid) for x in residuals)) ** 2
    n = Counter(r["boss"] for r in rows)
    seen = [b for b in pool if n[b] > 0]
    if not seen:
        return {}
    b = {e: effects["boss"][e] for e in seen}
    center = statistics.median(b.values())
    tau2 = max(
        1e-6,
        statistics.pvariance(b.values()) - statistics.mean(sigma2 / n[e] for e in seen),
    )
    k = sigma2 / tau2
    return {
        e: (math.exp(mu + center + (b[e] - center) * n[e] / (n[e] + k)), n[e])
        for e in seen
    }


def apply_weights(tags_text: str, weights: Mapping[int, float]) -> str:
    """Set ``boss.weight`` for ``weights``; everything else round-trips."""
    data = json.loads(tags_text)
    for eid, weight in weights.items():
        data[str(eid)]["boss"]["weight"] = weight
    return json.dumps(data, indent=2) + "\n"


async def load_rows() -> dict[str, list[dict[str, Any]]]:
    """Per-job fit rows from the racing database."""
    tags = load_tags(TAGS_PATH)
    names = name_index(
        tags,
        parse_boss_key_names(ENEMY_TXT_PATH),
        parse_boss_extra_names(ENEMY_TXT_PATH),
    )
    phases = parse_boss_phases(ENEMY_TXT_PATH)
    conn = await asyncpg.connect(DB_URL)
    try:
        seeds = {
            str(r["id"]): (r["pool_name"], json.loads(r["graph_json"]))
            for r in await conn.fetch("""
                SELECT s.id, s.pool_name, s.graph_json::text AS graph_json
                FROM seeds s
                WHERE EXISTS (SELECT 1 FROM races r JOIN participants p ON p.race_id = r.id
                              WHERE r.seed_id = s.id AND p.zone_history IS NOT NULL)
            """)
        }
        participants = await conn.fetch("""
            SELECT p.user_id::text AS uid, p.status, p.igt_ms,
                   p.zone_history::text AS zh, r.seed_id::text AS sid
            FROM participants p JOIN races r ON p.race_id = r.id
            WHERE p.zone_history IS NOT NULL AND p.zone_history::text NOT IN ('null', '[]')
        """)
    finally:
        await conn.close()
    rows: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for p in participants:
        if p["sid"] not in seeds:
            continue
        pool, graph = seeds[p["sid"]]
        nodes = graph.get("nodes", {})
        history = json.loads(p["zh"])
        if not history:
            continue
        for clear in boss_clears(history, p["igt_ms"], p["status"], nodes):
            node = nodes[clear.node_id]
            boss = attribute(node, graph.get("enemy_assignments"), names, phases)
            if boss is None or clear.minutes <= 0:
                continue
            rows[BOSS_JOBS[node["type"]]].append(
                {
                    "y": math.log(clear.minutes),
                    "arena": resolve_entity_id(node["defeat_flag"]),
                    "boss": boss,
                    "tier": min(node.get("tier") or 0, TIER_CAP),
                    "user": p["uid"],
                    "pool": pool,
                }
            )
    return rows


def current_pools() -> dict[str, dict[int, Any]]:
    """speedfog's minor and major candidate pools (DLC included)."""
    tags = load_tags(TAGS_PATH)
    phases = parse_boss_phases(ENEMY_TXT_PATH)
    clusters = load_clusters(CLUSTERS_PATH)

    def ids(cluster_type: str) -> list[int]:
        return [
            resolve_entity_id(c.defeat_flag)
            for c in clusters.get_by_type(cluster_type)
            if c.defeat_flag
        ]

    majors, minors = ids("major_boss"), ids("boss_arena")
    return {
        "minor": _compose_pool(
            tags, "minor", minors, other_vanilla_ids=majors, phase_mapping=phases
        ),
        "major": _compose_pool(
            tags, "major", majors, other_vanilla_ids=minors, phase_mapping=phases
        ),
    }


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--write",
        action="store_true",
        help=f"write the suggested weights into {TAGS_PATH}",
    )
    args = parser.parse_args()

    tags = load_tags(TAGS_PATH)
    rows = await load_rows()
    suggested: dict[int, float] = {}
    for job, pool in current_pools().items():
        job_rows = rows.get(job, [])
        if not job_rows:
            print(f"== {job}: no data")
            continue
        mu, effects = fit_effects(job_rows)
        weights = shrunk_weights(job_rows, mu, effects, pool)
        print(
            f"== {job}: {len(job_rows)} clears, {len(weights)}/{len(pool)} pool "
            f"bosses measured, typical node {math.exp(mu):.2f} min"
        )
        print(f"{'boss':45} {'current':>7} {'suggest':>7} {'n':>5}")
        for eid, (minutes, n) in sorted(weights.items(), key=lambda x: -x[1][0]):
            weight = max(0.1, round(minutes, 1))
            suggested[eid] = weight
            current = tags[eid].boss.weight
            flag = "  *" if abs(weight - current) >= 0.2 else ""
            print(f"{tags[eid].name[:45]:45} {current:7.1f} {weight:7.1f} {n:5d}{flag}")
        missing = [tags[e].name for e in pool if e not in weights]
        if missing:
            print(f"   no data (weight left as is): {', '.join(missing)}")
    if args.write:
        TAGS_PATH.write_text(apply_weights(TAGS_PATH.read_text(), suggested))
        print(f"Wrote {len(suggested)} weights to {TAGS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
