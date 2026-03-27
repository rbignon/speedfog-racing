"""Stats computation: ELO ratings and behavioral traits."""

import logging
from collections.abc import Sequence
from difflib import SequenceMatcher
from math import sqrt
from statistics import median
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import (
    EloHistory,
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
    User,
)

logger = logging.getLogger(__name__)

K_FACTOR = 32
STARTING_ELO = 1500.0
MIN_RACES_FOR_DISPLAY = 3
DOMINANT_PERCENTILE_THRESHOLD = 0.5  # Must be in top 50% on at least one trait
BOSS_NODE_TYPES = {"boss_arena", "major_boss", "final_boss"}
MIN_RACES_FOR_TRAITS = 3


def compute_elo_deltas(
    players: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute ELO rating changes for all players in a race.

    Each player dict must have: user_id, elo, igt_ms, finished (bool).
    Players with finished=False are treated as abandoned (S=0 against finishers).
    Returns a dict mapping user_id to delta (float).
    """
    n = len(players)
    if n < 2:
        return {p["user_id"]: 0.0 for p in players}

    finisher_igts = [p["igt_ms"] for p in players if p["finished"]]
    if finisher_igts:
        ref_time = median(finisher_igts) * 0.3
    else:
        ref_time = 1.0  # Avoid division by zero; all abandoned

    deltas: dict[str, float] = {p["user_id"]: 0.0 for p in players}

    for i in range(n):
        for j in range(i + 1, n):
            a, b = players[i], players[j]
            ea = 1.0 / (1.0 + 10.0 ** ((b["elo"] - a["elo"]) / 400.0))
            eb = 1.0 - ea

            sa, sb = _actual_scores(a, b, ref_time)

            deltas[a["user_id"]] += K_FACTOR * (sa - ea)
            deltas[b["user_id"]] += K_FACTOR * (sb - eb)

    for uid in deltas:
        deltas[uid] /= n - 1

    return deltas


def _actual_scores(a: dict[str, Any], b: dict[str, Any], ref_time: float) -> tuple[float, float]:
    """Compute actual scores for a pair with margin of victory."""
    a_fin, b_fin = a["finished"], b["finished"]

    if a_fin and b_fin:
        gap = abs(a["igt_ms"] - b["igt_ms"])
        margin = min(gap / ref_time, 1.0) if ref_time > 0 else 0.0
        if a["igt_ms"] <= b["igt_ms"]:
            return 0.5 + 0.5 * margin, 0.5 - 0.5 * margin
        else:
            return 0.5 - 0.5 * margin, 0.5 + 0.5 * margin
    elif a_fin and not b_fin:
        return 1.0, 0.0
    elif not a_fin and b_fin:
        return 0.0, 1.0
    else:
        return 0.5, 0.5


async def update_elo_ratings(race_id: Any, db: AsyncSession) -> None:
    """Compute and persist ELO changes for a finished race. Idempotent."""
    existing = await db.execute(select(EloHistory.id).where(EloHistory.race_id == race_id).limit(1))
    if existing.scalar_one_or_none() is not None:
        return

    race = await db.get(Race, race_id, options=[selectinload(Race.participants)])
    if race is None:
        return

    players: list[dict[str, Any]] = []
    for participant in race.participants:
        if participant.status == ParticipantStatus.FINISHED:
            players.append(
                {
                    "user_id": participant.user_id,
                    "igt_ms": participant.igt_ms,
                    "finished": True,
                }
            )
        elif participant.status == ParticipantStatus.ABANDONED and participant.igt_ms > 0:
            players.append(
                {
                    "user_id": participant.user_id,
                    "igt_ms": participant.igt_ms,
                    "finished": False,
                }
            )

    if len(players) < 2:
        return

    user_ids = [p["user_id"] for p in players]
    users_result = await db.execute(select(User).where(User.id.in_(user_ids)))
    users_by_id = {u.id: u for u in users_result.scalars().all()}

    # Filter to players whose users still exist (defensive against deleted users)
    players = [p for p in players if p["user_id"] in users_by_id]
    if len(players) < 2:
        return

    for p in players:
        p["elo"] = users_by_id[p["user_id"]].elo_rating

    deltas = compute_elo_deltas(players)

    logger.debug("ELO update for race %s: %d players", race_id, len(players))

    for p in players:
        user = users_by_id[p["user_id"]]
        delta = deltas[p["user_id"]]
        elo_before = user.elo_rating
        user.elo_rating = elo_before + delta
        user.elo_races += 1
        db.add(
            EloHistory(
                user_id=user.id,
                race_id=race_id,
                elo_before=elo_before,
                elo_after=user.elo_rating,
                delta=delta,
            )
        )

    await db.commit()


async def update_player_traits(race_id: Any, db: AsyncSession) -> None:
    """Recompute trait scores for all participants of a finished race."""
    race = await db.get(Race, race_id, options=[selectinload(Race.participants)])
    if race is None:
        return

    user_ids = [
        p.user_id
        for p in race.participants
        if p.status == ParticipantStatus.FINISHED
        or (p.status == ParticipantStatus.ABANDONED and p.igt_ms > 0)
    ]

    for user_id in user_ids:
        await _recompute_traits_for_user(user_id, db)

    await db.commit()


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


async def _recompute_traits_for_user(user_id: Any, db: AsyncSession) -> None:
    """Recompute all trait scores for a single user across all their races."""
    all_participations = (
        (
            await db.execute(
                select(Participant)
                .where(
                    Participant.user_id == user_id,
                    Participant.status == ParticipantStatus.FINISHED,
                )
                .options(
                    selectinload(Participant.race).selectinload(Race.participants),
                    selectinload(Participant.race).selectinload(Race.seed),
                )
            )
        )
        .scalars()
        .all()
    )

    # Count global stats
    total_participated = (
        await db.execute(
            select(func.count()).where(
                Participant.user_id == user_id,
                Participant.status.in_([ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED]),
                Participant.igt_ms > 0,
            )
        )
    ).scalar() or 0

    total_abandoned_playing = (
        await db.execute(
            select(func.count()).where(
                Participant.user_id == user_id,
                Participant.status == ParticipantStatus.ABANDONED,
                Participant.igt_ms > 0,
            )
        )
    ).scalar() or 0

    total_finished = len(all_participations)

    # Accumulate per-race trait scores
    rusher_scores: list[float] = []
    cautious_scores: list[float] = []
    explorer_scores: list[float] = []
    pathfinder_scores: list[float] = []
    boss_slayer_scores: list[float] = []
    death_percentiles: list[float] = []

    for pp in all_participations:
        race_obj = pp.race
        seed = race_obj.seed
        if seed is None:
            continue

        finishers = [rp for rp in race_obj.participants if rp.status == ParticipantStatus.FINISHED]
        if len(finishers) < 2:
            continue

        graph = seed.graph_json
        nodes = graph.get("nodes", {})
        total_nodes = len(nodes)
        igts = [f.igt_ms for f in finishers]
        deaths = [f.death_count for f in finishers]
        player_idx = next(i for i, f in enumerate(finishers) if f.user_id == user_id)

        rusher_scores.append(compute_rusher_score(igts, deaths, player_idx))
        cautious_scores.append(compute_cautious_score(igts, deaths, player_idx))

        history = pp.zone_history or []
        visited = {e.get("node_id", "") for e in history if e.get("node_id")}
        explorer_scores.append(compute_explorer_score(visited, total_nodes, history))

        # Pathfinder: sequence-based divergence (first-visit order, no revisits)
        player_path = _first_visit_path(history)
        other_paths: list[list[str]] = []
        for f in finishers:
            if f.user_id != user_id:
                other_path = _first_visit_path(f.zone_history or [])
                if other_path:
                    other_paths.append(other_path)
        pathfinder_scores.append(compute_pathfinder_score(player_path, other_paths))

        # Boss slayer: collect per-boss death lists for ranking
        # Use last visit per boss per finisher (deaths accumulate on last entry)
        player_boss_deaths: dict[str, int] = {}
        boss_all_deaths: dict[str, list[int]] = {}
        for f in finishers:
            finisher_boss_deaths: dict[str, int] = {}
            for e in f.zone_history or []:
                nid = e.get("node_id", "")
                node_info = nodes.get(nid, {})
                if node_info.get("type") in BOSS_NODE_TYPES:
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

    scores = {
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

    # Upsert raw scores only; dominant_trait and dominant_description
    # are resolved globally by resolve_dominant_traits()
    existing = await db.get(PlayerTraitScores, user_id)
    if existing:
        for key, val in scores.items():
            setattr(existing, key, val)
    else:
        db.add(
            PlayerTraitScores(
                user_id=user_id,
                **scores,
            )
        )


def _compute_ranks(values: Sequence[int | float]) -> list[float]:
    """Compute 1-indexed ranks with average rank for ties."""
    n = len(values)
    sorted_indices = sorted(range(n), key=lambda i: values[i])
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

    n = len(all_scores)

    # Build per-trait percentiles: {user_id: {trait: percentile}}
    percentiles: dict[Any, dict[str, float]] = {s.user_id: {} for s in all_scores}

    for trait in TRAIT_KEYS:
        values = [getattr(s, trait) for s in all_scores]
        ranks = _compute_ranks_desc(values)
        for i, s in enumerate(all_scores):
            # Convert rank to percentile: (rank - 1) / (n - 1) if n > 1
            # 0.0 = best (rank 1), 1.0 = worst (rank n)
            percentiles[s.user_id][trait] = (ranks[i] - 1) / (n - 1) if n > 1 else 0.0

    for s in all_scores:
        user_pcts = percentiles[s.user_id]
        raw_scores = {t: getattr(s, t) for t in TRAIT_KEYS}

        # Find best trait: lowest percentile, then highest raw score for ties
        best_trait = min(
            TRAIT_KEYS,
            key=lambda t: (user_pcts[t], -raw_scores[t]),
        )
        best_pct = user_pcts[best_trait]

        if best_pct <= DOMINANT_PERCENTILE_THRESHOLD and raw_scores[best_trait] > 0:
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

    await db.commit()


def _compute_ranks_desc(values: list[int | float]) -> list[float]:
    """Compute 1-indexed ranks for descending order (highest value = rank 1).

    Uses average rank for ties, same as _compute_ranks but reversed.
    """
    n = len(values)
    sorted_indices = sorted(range(n), key=lambda i: values[i], reverse=True)
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


async def recalculate_all_stats(db: AsyncSession) -> None:
    """Clear all ELO/trait data and replay from scratch."""
    await db.execute(delete(EloHistory))
    await db.execute(delete(PlayerTraitScores))

    all_users = (await db.execute(select(User))).scalars().all()
    for u in all_users:
        u.elo_rating = STARTING_ELO
        u.elo_races = 0
    await db.commit()

    race_ids = (
        (
            await db.execute(
                select(Race.id)
                .where(Race.status == RaceStatus.FINISHED)
                .order_by(Race.started_at.asc())
            )
        )
        .scalars()
        .all()
    )

    for race_id in race_ids:
        await update_elo_ratings(race_id, db)
        await update_player_traits(race_id, db)

    # After all per-user raw scores are computed, resolve dominant traits
    # using percentile ranking across all players
    await resolve_dominant_traits(db)
