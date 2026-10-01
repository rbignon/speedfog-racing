"""Suggest boss.weight values for speedfog's data/boss_arena_tags.json.

A boss node's clear time mixes the arena (approach, exit), the boss fight,
the scaling tier, the player and the pool's power curve. Boss randomization
decorrelates bosses from arenas, so a robust additive fit of the log clear
time (arena + boss-by-band + tier + user + pool, multi-factor median
polish; bands from speedfog's weight_band) isolates the boss. Each factor is centered on its observation-weighted
median, so a band weight is the median node time for that boss in that
band under typical arena, player and pool, with the band's common shift
removed (minutes at a mid-run tier): only the boss's own tier sensitivity
varies across bands. Weights compare bosses; they are indicative in
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
from speedfog.boss_arena_constraints import (  # noqa: E402
    WEIGHT_BANDS,
    load_tags,
    weight_band,
)
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
FACTORS = ("arena", "bossband", "tier", "user", "pool")
# Tiers above this are rare; pooling them keeps their factor estimable.
TIER_CAP = 24
# Bosses measured on fewer clears get the job's median weight: an estimate
# that noisy should neither block nor be blocked by the spread rule.
MIN_SAMPLES = 20


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


def band_weights(
    rows: Sequence[Mapping[str, Any]],
    mu: float,
    effects: Mapping[str, Mapping[Any, float]],
    pool: Iterable[Any],
    min_samples: int = MIN_SAMPLES,
) -> dict[Any, tuple[dict[str, float], int]]:
    """``{boss: ({band: minutes}, n)}`` for the pool bosses seen in ``rows``.

    Each band's common shift (the observation-weighted median boss-band
    effect) is removed and the mid band's added back, so a weight reads as
    minutes at a mid-run tier and only the boss's own tier sensitivity
    varies across bands. The boss's overall relative effect is shrunk toward
    the pool median by ``n / (n + k)``, each band toward that overall by
    ``n_band / (n_band + k)``; a band with fewer than ``min_samples`` rows
    takes the overall value. ``k = sigma^2 / tau^2`` as in a single-weight
    fit (robust residual variance over between-boss variance).
    """
    bossband = effects["bossband"]
    shift = {
        band: statistics.median(
            bossband[r["bossband"]] for r in rows if r["bossband"][1] == band
        )
        for band in WEIGHT_BANDS
        if any(r["bossband"][1] == band for r in rows)
    }
    residuals = [r["y"] - mu - sum(effects[f][r[f]] for f in effects) for r in rows]
    mid = statistics.median(residuals)
    sigma2 = (1.4826 * statistics.median(abs(x - mid) for x in residuals)) ** 2
    n_band = Counter(r["bossband"] for r in rows)
    n = Counter(r["bossband"][0] for r in rows)
    seen = [b for b in pool if n[b] > 0]
    if not seen:
        return {}
    rel = {
        b: {
            band: bossband[(b, band)] - shift[band]
            for band in WEIGHT_BANDS
            if n_band[(b, band)] > 0
        }
        for b in seen
    }
    overall = {
        b: sum(rel[b][band] * n_band[(b, band)] for band in rel[b]) / n[b] for b in seen
    }
    center = statistics.median(overall.values())
    tau2 = max(
        1e-6,
        statistics.pvariance(overall.values())
        - statistics.mean(sigma2 / n[b] for b in seen),
    )
    k = sigma2 / tau2
    ref = mu + shift.get("mid", 0.0)
    out: dict[Any, tuple[dict[str, float], int]] = {}
    for b in seen:
        base = center + (overall[b] - center) * n[b] / (n[b] + k)
        minutes = {}
        for band in WEIGHT_BANDS:
            nb = n_band[(b, band)]
            dev = 0.0
            if nb >= min_samples:
                dev = (rel[b][band] - overall[b]) * nb / (nb + k)
            minutes[band] = math.exp(ref + base + dev)
        out[b] = (minutes, n[b])
    return out


def rounded_weights(
    weights: Mapping[Any, tuple[Mapping[str, float], int]],
    min_samples: int = MIN_SAMPLES,
) -> dict[Any, tuple[dict[str, float], bool]]:
    """``{boss: ({band: weight}, thin)}`` rounded to 0.1 minute (at least 0.1).

    A thin boss (fewer than ``min_samples`` clears) gets, in each band, the
    median of the well-measured bosses instead of its own estimate.
    """
    solid = [minutes for minutes, n in weights.values() if n >= min_samples]
    medians = (
        {band: statistics.median(m[band] for m in solid) for band in WEIGHT_BANDS}
        if solid
        else None
    )
    out: dict[Any, tuple[dict[str, float], bool]] = {}
    for boss, (minutes, n) in weights.items():
        thin = n < min_samples
        source = medians if thin and medians is not None else minutes
        out[boss] = (
            {band: max(0.1, round(source[band], 1)) for band in WEIGHT_BANDS},
            thin,
        )
    return out


def apply_weights(tags_text: str, weights: Mapping[int, Mapping[str, float]]) -> str:
    """Set ``boss.weight`` (band objects) for ``weights``; everything else round-trips."""
    data = json.loads(tags_text)
    for eid, weight in weights.items():
        data[str(eid)]["boss"]["weight"] = dict(weight)
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
                    "bossband": (boss, weight_band(node.get("tier") or 0)),
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
    suggested: dict[int, dict[str, float]] = {}
    for job, pool in current_pools().items():
        job_rows = rows.get(job, [])
        if not job_rows:
            print(f"== {job}: no data")
            continue
        mu, effects = fit_effects(job_rows)
        weights = band_weights(job_rows, mu, effects, pool)
        print(
            f"== {job}: {len(job_rows)} clears, {len(weights)}/{len(pool)} pool "
            f"bosses measured, typical node {math.exp(mu):.2f} min"
        )
        print(f"{'boss':45} {'current e/m/l':>15} {'suggested e/m/l':>15} {'n':>5}")
        final = rounded_weights(weights)
        for eid, (bands, thin) in sorted(
            final.items(), key=lambda x: -max(x[1][0].values())
        ):
            suggested[eid] = bands
            current = dict(zip(WEIGHT_BANDS, tags[eid].boss.weights, strict=True))
            moved = max(abs(bands[b] - current[b]) for b in WEIGHT_BANDS) >= 0.2
            flag = ("  *" if moved else "") + (
                f"  (thin, n<{MIN_SAMPLES}: band medians)" if thin else ""
            )
            cur = "/".join(f"{current[b]:.1f}" for b in WEIGHT_BANDS)
            sug = "/".join(f"{bands[b]:.1f}" for b in WEIGHT_BANDS)
            print(
                f"{tags[eid].name[:45]:45} {cur:>15} {sug:>15} {weights[eid][1]:5d}{flag}"
            )
        missing = [tags[e].name for e in pool if e not in weights]
        if missing:
            print(f"   no data (weight left as is): {', '.join(missing)}")
    if args.write:
        TAGS_PATH.write_text(apply_weights(TAGS_PATH.read_text(), suggested))
        print(f"Wrote {len(suggested)} weights to {TAGS_PATH}")


if __name__ == "__main__":
    asyncio.run(main())
