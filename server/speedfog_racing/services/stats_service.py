"""Stats computation: behavioral traits."""

import asyncio
import json
import logging
from collections.abc import Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from math import sqrt
from typing import Any

from sqlalchemy import Row, Text, cast, delete, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.database import async_session_maker
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
)
from speedfog_racing.services.seed_nodes import SeedNodes, load_seed_nodes

logger = logging.getLogger(__name__)

DOMINANT_PERCENTILE_THRESHOLD = 0.5  # Must be in top 50% on at least one trait
BOSS_NODE_TYPES = {"boss_arena", "major_boss", "final_boss"}
MIN_RACES_FOR_TRAITS = 3


@dataclass(frozen=True)
class _Finisher:
    """The fields of one finished participation that trait scoring reads."""

    user_id: Any
    igt_ms: int
    death_count: int
    zone_history: list[dict[str, Any]]


# Participations whose user gets trait scores: finished, or abandoned after
# actually starting (in-game time recorded).
_SCORED_PARTICIPATION = or_(
    Participant.status == ParticipantStatus.FINISHED,
    (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
)


async def update_player_traits(race_id: Any, db: AsyncSession) -> None:
    """Recompute trait scores for all participants of a finished race."""
    user_ids = (
        (
            await db.execute(
                select(Participant.user_id)
                .distinct()
                .where(Participant.race_id == race_id, _SCORED_PARTICIPATION)
            )
        )
        .scalars()
        .all()
    )
    await _recompute_traits_for_users(user_ids, db)
    await db.commit()


async def _recompute_traits_for_users(user_ids: Sequence[Any], db: AsyncSession) -> None:
    """Recompute and stage (without committing) the raw trait scores of users.

    Each score averages the user's whole race history, so the inputs cover
    every finished race of every user. They are read once for the whole
    batch with narrow column selects (seed graphs come from the cached
    SeedNodes projection instead of graph_json), and the CPU-bound scoring
    runs in a worker thread: a veteran's history takes seconds to score, and
    the event loop serves every WebSocket and request meanwhile.
    """
    if not user_ids:
        return

    history_race_ids = select(Participant.race_id).where(
        Participant.user_id.in_(user_ids),
        Participant.status == ParticipantStatus.FINISHED,
    )

    # Every finisher of every race a user finished: the users' own finished
    # participations come from the same rows (one snapshot), and they are
    # ranked against all finishers, batch members or not. zone_history is
    # fetched as raw JSON text: the driver would otherwise decode thousands of
    # histories inside its network callbacks, on the loop.
    finisher_rows = (
        await db.execute(
            select(
                Participant.race_id,
                Participant.user_id,
                Participant.igt_ms,
                Participant.death_count,
                cast(Participant.zone_history, Text),
            ).where(
                Participant.status == ParticipantStatus.FINISHED,
                Participant.race_id.in_(history_race_ids),
            )
        )
    ).all()
    finishers_by_race = await asyncio.to_thread(_group_finishers, finisher_rows)
    races_by_user: dict[Any, list[Any]] = {uid: [] for uid in user_ids}
    for finisher in finisher_rows:
        if finisher.user_id in races_by_user:
            races_by_user[finisher.user_id].append(finisher.race_id)

    seed_by_race = {
        rid: sid
        for rid, sid in (
            await db.execute(select(Race.id, Race.seed_id).where(Race.id.in_(history_race_ids)))
        ).all()
        if sid is not None
    }
    seed_nodes = await load_seed_nodes(db, seed_by_race.values())
    nodes_by_race = {rid: seed_nodes[sid] for rid, sid in seed_by_race.items() if sid in seed_nodes}

    # Counts over every run with in-game time, finished or abandoned.
    participated: dict[Any, int] = {}
    abandoned_playing: dict[Any, int] = {}
    for uid, status, count in (
        await db.execute(
            select(Participant.user_id, Participant.status, func.count())
            .where(
                Participant.user_id.in_(user_ids),
                Participant.status.in_([ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED]),
                Participant.igt_ms > 0,
            )
            .group_by(Participant.user_id, Participant.status)
        )
    ).all():
        participated[uid] = participated.get(uid, 0) + count
        if status == ParticipantStatus.ABANDONED:
            abandoned_playing[uid] = count

    existing = {
        row.user_id: row
        for row in (
            await db.execute(
                select(PlayerTraitScores).where(PlayerTraitScores.user_id.in_(user_ids))
            )
        ).scalars()
    }
    for user_id in user_ids:
        scores = await asyncio.to_thread(
            _compute_trait_scores,
            user_id,
            races_by_user[user_id],
            finishers_by_race,
            nodes_by_race,
            participated.get(user_id, 0),
            abandoned_playing.get(user_id, 0),
        )
        # Upsert raw scores only; dominant_trait and dominant_description
        # are resolved globally by resolve_dominant_traits()
        row = existing.get(user_id)
        if row is not None:
            for key, val in scores.items():
                setattr(row, key, val)
        else:
            db.add(PlayerTraitScores(user_id=user_id, **scores))


def _group_finishers(rows: Sequence[Row[Any]]) -> dict[Any, list[_Finisher]]:
    """Group finisher rows by race, decoding each JSON-text zone_history."""
    by_race: dict[Any, list[_Finisher]] = {}
    for race_id, user_id, igt_ms, death_count, zone_history_json in rows:
        history = json.loads(zone_history_json) if zone_history_json else None
        by_race.setdefault(race_id, []).append(
            _Finisher(user_id, igt_ms, death_count, history or [])
        )
    return by_race


def _first_visit_path(zh: list[dict[str, Any]]) -> list[str]:
    """Extract first-visit node order from zone_history, ignoring revisits."""
    seen: set[str] = set()
    path: list[str] = []
    for e in zh:
        nid = e.get("node_id", "")
        if nid and nid not in seen:
            seen.add(nid)
            path.append(nid)
    return path


def _compute_trait_scores(
    user_id: Any,
    race_ids: Sequence[Any],
    finishers_by_race: dict[Any, list[_Finisher]],
    nodes_by_race: dict[Any, SeedNodes],
    total_participated: int,
    total_abandoned_playing: int,
) -> dict[str, int]:
    """Score one user's traits over their finished races (pure, CPU-bound).

    ``race_ids`` lists the user's finished participations. Races without a
    seed projection or with fewer than two finishers contribute no per-race
    score but still count as finished for the resilient/rage-quit rates.
    """
    total_finished = len(race_ids)

    # Accumulate per-race trait scores
    rusher_scores: list[float] = []
    cautious_scores: list[float] = []
    explorer_scores: list[float] = []
    pathfinder_scores: list[float] = []
    boss_slayer_scores: list[float] = []
    death_percentiles: list[float] = []

    for race_id in race_ids:
        seed_nodes = nodes_by_race.get(race_id)
        if seed_nodes is None:
            continue

        finishers = finishers_by_race.get(race_id, [])
        if len(finishers) < 2:
            continue

        nodes = seed_nodes.nodes
        total_nodes = len(nodes)
        igts = [f.igt_ms for f in finishers]
        deaths = [f.death_count for f in finishers]
        player_idx = next(i for i, f in enumerate(finishers) if f.user_id == user_id)

        rusher_scores.append(compute_rusher_score(igts, deaths, player_idx))
        cautious_scores.append(compute_cautious_score(igts, deaths, player_idx))

        history = finishers[player_idx].zone_history
        visited = {e.get("node_id", "") for e in history if e.get("node_id")}
        explorer_scores.append(compute_explorer_score(visited, total_nodes, history))

        # Pathfinder: sequence-based divergence (first-visit order, no revisits)
        player_path = _first_visit_path(history)
        other_paths: list[list[str]] = []
        for f in finishers:
            if f.user_id != user_id:
                other_path = _first_visit_path(f.zone_history)
                if other_path:
                    other_paths.append(other_path)
        pathfinder_scores.append(compute_pathfinder_score(player_path, other_paths))

        # Boss slayer: collect per-boss death lists for ranking
        # Use last visit per boss per finisher (deaths accumulate on last entry)
        player_boss_deaths: dict[str, int] = {}
        boss_all_deaths: dict[str, list[int]] = {}
        for f in finishers:
            finisher_boss_deaths: dict[str, int] = {}
            for e in f.zone_history:
                nid = e.get("node_id", "")
                node_info = nodes.get(nid)
                if node_info is not None and node_info.type in BOSS_NODE_TYPES:
                    finisher_boss_deaths[nid] = e.get("deaths", 0)
            for nid, d in finisher_boss_deaths.items():
                boss_all_deaths.setdefault(nid, []).append(d)
                if f.user_id == user_id:
                    player_boss_deaths[nid] = d
        boss_slayer_scores.append(compute_boss_slayer_score(player_boss_deaths, boss_all_deaths))

        # Resilient: death rank percentile among finishers
        n_fin = len(finishers)
        if n_fin >= 2:
            death_ranks = _compute_ranks(deaths)
            death_percentiles.append((death_ranks[player_idx] - 1) / (n_fin - 1))

    def avg_or_zero(vals: list[float]) -> int:
        if len(vals) < MIN_RACES_FOR_TRAITS:
            return 0
        return round(sum(vals) / len(vals) * 100)

    return {
        "rusher": avg_or_zero(rusher_scores),
        "cautious": avg_or_zero(cautious_scores),
        "explorer": avg_or_zero(explorer_scores),
        "pathfinder": avg_or_zero(pathfinder_scores),
        "boss_slayer": avg_or_zero(boss_slayer_scores),
        "resilient": round(
            compute_resilient_score(death_percentiles, total_finished, total_participated)
        )
        if total_finished >= MIN_RACES_FOR_TRAITS
        else 0,
        "rage_quitter": round(
            compute_rage_quitter_score(total_abandoned_playing, total_participated)
        )
        if total_finished >= MIN_RACES_FOR_TRAITS
        else 0,
    }


def _compute_ranks(values: Sequence[int | float], *, descending: bool = False) -> list[float]:
    """Compute 1-indexed ranks with average rank for ties.

    By default, lowest value = rank 1. With descending=True, highest value = rank 1.
    """
    n = len(values)
    sorted_indices = sorted(range(n), key=lambda i: values[i], reverse=descending)
    ranks = [0.0] * n
    i = 0
    while i < n:
        j = i
        while j < n - 1 and values[sorted_indices[j + 1]] == values[sorted_indices[i]]:
            j += 1
        avg_rank = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[sorted_indices[k]] = avg_rank
        i = j + 1
    return ranks


def compute_rusher_score(igts: list[int], deaths: list[int], player_index: int) -> float:
    """Score how much a player rushes: fast IGT but many deaths."""
    n = len(igts)
    if n < 2:
        return 0.0
    igt_ranks = _compute_ranks(igts)
    death_ranks = _compute_ranks(deaths)
    raw = max(0.0, death_ranks[player_index] - igt_ranks[player_index]) / (n - 1)
    raw = min(raw, 1.0)
    return float(raw**0.4)


def compute_cautious_score(igts: list[int], deaths: list[int], player_index: int) -> float:
    """Score how cautious a player is: few deaths but slow IGT."""
    n = len(igts)
    if n < 2:
        return 0.0
    igt_ranks = _compute_ranks(igts)
    death_ranks = _compute_ranks(deaths)
    raw = max(0.0, igt_ranks[player_index] - death_ranks[player_index]) / (n - 1)
    raw = min(raw, 1.0)
    return float(raw**0.4)


def compute_explorer_score(
    visited_nodes: set[str], total_nodes: int, history: list[dict[str, Any]]
) -> float:
    """Score exploration tendency: sqrt-scaled node coverage weighted with backtracking rate."""
    if total_nodes == 0 or not history:
        return 0.0
    coverage = sqrt(len(visited_nodes) / total_nodes)
    seen: set[str] = set()
    backtracks = 0
    for entry in history:
        nid = entry.get("node_id", "")
        if nid in seen:
            backtracks += 1
        seen.add(nid)
    backtrack_rate = backtracks / len(history) if history else 0.0
    return 0.6 * coverage + 0.4 * backtrack_rate


def compute_pathfinder_score(player_path: list[str], other_paths: list[list[str]]) -> float:
    """Score path uniqueness: how different the player's route order is from others."""
    if not player_path or not other_paths:
        return 0.0
    similarities = [SequenceMatcher(None, player_path, other).ratio() for other in other_paths]
    avg_similarity = sum(similarities) / len(similarities)
    raw = 1.0 - avg_similarity
    return float(raw**0.6)


def compute_boss_slayer_score(
    player_boss_deaths: dict[str, int],
    boss_all_deaths: dict[str, list[int]],
) -> float:
    """Score boss efficiency: rank-based, weighted by boss difficulty (avg deaths)."""
    if not player_boss_deaths or not boss_all_deaths:
        return 0.0
    total_weight = 0.0
    weighted_score = 0.0
    for boss_id, player_deaths in player_boss_deaths.items():
        all_deaths = boss_all_deaths.get(boss_id)
        if not all_deaths or len(all_deaths) < 2:
            continue
        n = len(all_deaths)
        ranks = _compute_ranks(all_deaths)
        # Find player's rank (ties handled by _compute_ranks giving average rank)
        player_rank = None
        for idx, d in enumerate(all_deaths):
            if d == player_deaths:
                player_rank = ranks[idx]
                break
        if player_rank is None:
            continue
        score = (n - player_rank) / (n - 1)
        # Weight by boss difficulty (average deaths across all players)
        weight = sum(all_deaths) / n
        if weight == 0:
            weight = 1.0
        weighted_score += score * weight
        total_weight += weight
    raw = weighted_score / total_weight if total_weight > 0 else 0.0
    return float(raw**1.4)


def compute_resilient_score(
    death_percentiles: list[float], finished_races: int, total_races: int
) -> float:
    """Score resilience (0-100): keeps finishing despite high death counts.

    death_percentiles: per finished race, (death_rank - 1) / (N - 1) among finishers.
    High value = more deaths than others. Weighted by completion rate.
    """
    if total_races == 0 or not death_percentiles:
        return 0.0
    avg_death_pct = sum(death_percentiles) / len(death_percentiles)
    completion_rate = finished_races / total_races
    return min(avg_death_pct * completion_rate * 100.0, 100.0)


def compute_rage_quitter_score(abandoned: int, total: int) -> float:
    """Score rage-quitting tendency (0-100): fraction of races abandoned."""
    if total < MIN_RACES_FOR_TRAITS:
        return 0.0
    return (abandoned / total) * 100.0


TRAIT_KEYS = [
    "rusher",
    "cautious",
    "explorer",
    "pathfinder",
    "boss_slayer",
    "resilient",
    "rage_quitter",
]


async def resolve_dominant_traits(db: AsyncSession) -> None:
    """Resolve dominant trait for all players using percentile ranking.

    For each trait, rank all players by raw score. Each player's dominant
    trait is the one where they rank best (lowest percentile). Ties in
    percentile are broken by higher raw score.
    """
    all_scores = (await db.execute(select(PlayerTraitScores))).scalars().all()
    if not all_scores:
        return

    # Only rank players with enough races for meaningful traits.
    # Players below the threshold keep their raw scores but get no
    # dominant trait (avoids inflating "among N players" with zeroes).
    qualified_user_ids: set[Any] = set()
    qualified_result = await db.execute(
        select(Participant.user_id)
        .where(Participant.status == ParticipantStatus.FINISHED)
        .group_by(Participant.user_id)
        .having(func.count() >= MIN_RACES_FOR_TRAITS)
    )
    for (uid,) in qualified_result:
        qualified_user_ids.add(uid)

    qualified_scores = [s for s in all_scores if s.user_id in qualified_user_ids]
    n = len(qualified_scores)

    # Build per-trait percentiles: {user_id: {trait: percentile}}
    percentiles: dict[Any, dict[str, float]] = {s.user_id: {} for s in qualified_scores}

    for trait in TRAIT_KEYS:
        values = [getattr(s, trait) for s in qualified_scores]
        ranks = _compute_ranks(values, descending=True)
        for i, s in enumerate(qualified_scores):
            # Convert rank to percentile: (rank - 1) / (n - 1) if n > 1
            # 0.0 = best (rank 1), 1.0 = worst (rank n)
            percentiles[s.user_id][trait] = (ranks[i] - 1) / (n - 1) if n > 1 else 0.0

    for s in qualified_scores:
        user_pcts = percentiles[s.user_id]
        raw_scores = {t: getattr(s, t) for t in TRAIT_KEYS}

        # Find best trait: lowest percentile, then highest raw score for ties
        best_trait = min(
            TRAIT_KEYS,
            key=lambda t: (user_pcts[t], -raw_scores[t]),
        )
        best_pct = user_pcts[best_trait]

        if best_pct <= DOMINANT_PERCENTILE_THRESHOLD and raw_scores[best_trait] > 0 and n >= 2:
            s.dominant_trait = best_trait
            # Human-readable: "Top X% among N players"
            top_pct = max(1, round(best_pct * 100))
            if best_pct == 0.0:
                s.dominant_description = f"#1 among {n} players"
            else:
                s.dominant_description = f"Top {top_pct}% among {n} players"
        else:
            s.dominant_trait = None
            s.dominant_description = None

    # Clear dominant trait for unqualified players
    for s in all_scores:
        if s.user_id not in qualified_user_ids:
            s.dominant_trait = None
            s.dominant_description = None

    await db.commit()


async def recalculate_all_stats(db: AsyncSession) -> None:
    """Refresh seed difficulty scores and rebuild all trait data from scratch."""
    from speedfog_racing.services.seed_difficulty import backfill_difficulty_scores

    await backfill_difficulty_scores(db)

    await db.execute(delete(PlayerTraitScores))
    await db.commit()

    # Scores only depend on each user's full history, so one batched pass over
    # every user a per-race replay would reach gives the same final state.
    user_ids = (
        (
            await db.execute(
                select(Participant.user_id)
                .distinct()
                .join(Race, Participant.race_id == Race.id)
                .where(
                    Race.status == RaceStatus.FINISHED,
                    Race.exclude_from_stats.is_(False),
                    _SCORED_PARTICIPATION,
                )
            )
        )
        .scalars()
        .all()
    )
    await _recompute_traits_for_users(user_ids, db)
    await db.commit()

    # After all per-user raw scores are computed, resolve dominant traits
    # using percentile ranking across all players
    await resolve_dominant_traits(db)


# Serialize concurrent trait recomputations. resolve_dominant_traits
# recalculates percentiles globally; two concurrent calls would each
# read partial data and overwrite each other's results.
_trait_lock = asyncio.Lock()


async def recompute_traits_for_race_async(race_id: Any) -> None:
    """Recompute trait scores for a finished race in its own DB session.

    Intended for fire-and-forget use via ``asyncio.create_task`` from the
    request-path race-finish handlers: the full history rescan would
    otherwise block the HTTP response for seconds on large histories.
    Errors are logged and swallowed. Serialized via ``_trait_lock`` so
    concurrent finishes do not corrupt dominant_trait percentiles.
    """
    try:
        async with _trait_lock:
            async with async_session_maker() as db:
                await update_player_traits(race_id, db)
                await resolve_dominant_traits(db)
    except Exception:
        logger.exception("Background trait recomputation failed for race %s", race_id)
