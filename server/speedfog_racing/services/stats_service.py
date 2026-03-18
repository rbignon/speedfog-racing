"""Stats computation: ELO ratings and behavioral traits."""

import logging
from collections.abc import Sequence
from datetime import UTC, datetime
from statistics import median
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import (
    EloHistory,
    ParticipantStatus,
    Race,
    User,
)

logger = logging.getLogger(__name__)

K_FACTOR = 32
STARTING_ELO = 1500.0
MIN_RACES_FOR_DISPLAY = 3
DOMINANT_TRAIT_THRESHOLD = 40


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

    for p in players:
        p["elo"] = users_by_id[p["user_id"]].elo_rating

    deltas = compute_elo_deltas(players)

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
                created_at=datetime.now(UTC),
            )
        )

    await db.commit()


async def update_player_traits(race_id: Any, db: AsyncSession) -> None:
    """Placeholder: compute and persist trait scores for race participants."""
    pass


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
    return min(raw, 1.0)


def compute_cautious_score(igts: list[int], deaths: list[int], player_index: int) -> float:
    """Score how cautious a player is: few deaths but slow IGT."""
    n = len(igts)
    if n < 2:
        return 0.0
    igt_ranks = _compute_ranks(igts)
    death_ranks = _compute_ranks(deaths)
    raw = max(0.0, igt_ranks[player_index] - death_ranks[player_index]) / (n - 1)
    return min(raw, 1.0)


def compute_explorer_score(
    visited_nodes: set[str], total_nodes: int, history: list[dict[str, Any]]
) -> float:
    """Score exploration tendency: node coverage weighted with backtracking rate."""
    if total_nodes == 0 or not history:
        return 0.0
    coverage = len(visited_nodes) / total_nodes
    seen: set[str] = set()
    backtracks = 0
    for entry in history:
        nid = entry.get("node_id", "")
        if nid in seen:
            backtracks += 1
        seen.add(nid)
    backtrack_rate = backtracks / len(history) if history else 0.0
    return 0.6 * coverage + 0.4 * backtrack_rate


def compute_pathfinder_score(player_nodes: set[str], others_nodes: set[str]) -> float:
    """Score how uniquely a player routes: fraction of visited nodes not seen by others."""
    if not player_nodes or not others_nodes:
        return 0.0
    unique = player_nodes - others_nodes
    return len(unique) / len(player_nodes)


def compute_boss_slayer_score(
    player_boss_deaths: dict[str, int],
    avg_boss_deaths: dict[str, float],
    boss_weights: dict[str, float],
) -> float:
    """Score boss efficiency: fewer deaths than average, weighted by boss difficulty."""
    if not player_boss_deaths or not avg_boss_deaths:
        return 0.0
    total_weight = 0.0
    weighted_score = 0.0
    for boss_id, player_deaths in player_boss_deaths.items():
        avg = avg_boss_deaths.get(boss_id, 0.0)
        weight = boss_weights.get(boss_id, 1.0)
        if avg > 0:
            score = max(0.0, 1.0 - player_deaths / avg)
        else:
            score = 1.0 if player_deaths == 0 else 0.0
        weighted_score += score * weight
        total_weight += weight
    return weighted_score / total_weight if total_weight > 0 else 0.0


def compute_resilient_score(
    finished_races: int, total_races: int, gap_ratios: list[float]
) -> float:
    """Score resilience (0-100): finishes races despite being far behind the leader."""
    if total_races == 0 or finished_races == 0:
        return 0.0
    completion_rate = finished_races / total_races
    avg_gap = sum(gap_ratios) / len(gap_ratios) if gap_ratios else 0.0
    raw = completion_rate * avg_gap
    return min(raw * 150.0, 100.0)


def compute_rage_quitter_score(abandoned: int, total: int) -> float:
    """Score rage-quitting tendency (0-100): fraction of races abandoned."""
    if total == 0:
        return 0.0
    return (abandoned / total) * 100.0
