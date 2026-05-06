"""Stats computation: ELO ratings and behavioral traits."""

import asyncio
import logging
from collections.abc import Sequence
from difflib import SequenceMatcher
from math import sqrt
from statistics import median
from typing import Any

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.database import async_session_maker
from speedfog_racing.models import (
    EloHistory,
    Participant,
    ParticipantStatus,
    PlayerTraitScores,
    Race,
    RaceStatus,
    Seed,
    User,
)

logger = logging.getLogger(__name__)

K_FACTOR = 32
K_FACTOR_PROVISIONAL = 48  # Higher K for players still calibrating
DIFFICULTY_INJECTION = 5.0  # Max ELO bonus/penalty per race from seed difficulty
REFERENCE_ELO = 1500.0  # Baseline for field strength weighting
STARTING_ELO = 1500.0
PROVISIONAL_THRESHOLD = 10  # Races needed for full ELO confidence
MIN_RACES_FOR_DISPLAY = 3
DOMINANT_PERCENTILE_THRESHOLD = 0.5  # Must be in top 50% on at least one trait
BOSS_NODE_TYPES = {"boss_arena", "major_boss", "final_boss"}
MIN_RACES_FOR_TRAITS = 3


def compute_elo_deltas(
    players: list[dict[str, Any]],
) -> dict[str, float]:
    """Compute ELO rating changes for all players in a race.

    Each player dict must have: user_id, elo, igt_ms, finished (bool).
    Optional: elo_races (int) for provisional confidence weighting and adaptive K factor.
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

            # Established players: scale by opponent confidence so that
            # matches against provisional players count less.
            # Provisional players: always get full delta (bootstrapping).
            conf_a = min(a.get("elo_races", PROVISIONAL_THRESHOLD) / PROVISIONAL_THRESHOLD, 1.0)
            conf_b = min(b.get("elo_races", PROVISIONAL_THRESHOLD) / PROVISIONAL_THRESHOLD, 1.0)
            a_is_established = a.get("elo_races", PROVISIONAL_THRESHOLD) >= PROVISIONAL_THRESHOLD
            b_is_established = b.get("elo_races", PROVISIONAL_THRESHOLD) >= PROVISIONAL_THRESHOLD
            weight_a = conf_b if a_is_established else 1.0
            weight_b = conf_a if b_is_established else 1.0
            k_a = K_FACTOR_PROVISIONAL if not a_is_established else K_FACTOR
            k_b = K_FACTOR_PROVISIONAL if not b_is_established else K_FACTOR
            deltas[a["user_id"]] += k_a * (sa - ea) * weight_a
            deltas[b["user_id"]] += k_b * (sb - eb) * weight_b

    # Normalize: established players by sum of opponent confidences
    # (prevents dilution from provisionals), others by n-1
    for p in players:
        uid = p["user_id"]
        is_established = p.get("elo_races", PROVISIONAL_THRESHOLD) >= PROVISIONAL_THRESHOLD
        if is_established:
            conf_sum = sum(
                min(other.get("elo_races", PROVISIONAL_THRESHOLD) / PROVISIONAL_THRESHOLD, 1.0)
                for other in players
                if other["user_id"] != uid
            )
            if conf_sum > 0:
                deltas[uid] /= max(conf_sum, 1.0)
        else:
            deltas[uid] /= n - 1

    return deltas


def apply_field_strength_weight(
    deltas: dict[str, float],
    player_elos: dict[str, float],
) -> dict[str, float]:
    """Scale ELO deltas by the average field strength.

    Strong fields (avg ELO > REFERENCE_ELO) amplify gains/losses.
    Weak fields dampen them. This accelerates rating divergence
    once difficulty injection starts separating pool averages.
    """
    if not player_elos:
        return deltas
    avg_elo = sum(player_elos.values()) / len(player_elos)
    weight = avg_elo / REFERENCE_ELO
    return {uid: delta * weight for uid, delta in deltas.items()}


def apply_difficulty_bonus(
    deltas: dict[str, float],
    difficulty_factor: float,
) -> dict[str, float]:
    """Add a uniform bonus/penalty based on seed difficulty.

    This intentionally breaks zero-sum: harder seeds inject positive
    ELO into the system, easier seeds remove it. Over time, players
    who race on harder seeds drift upward.
    """
    bonus = DIFFICULTY_INJECTION * (difficulty_factor - 1.0)
    return {uid: delta + bonus for uid, delta in deltas.items()}


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


async def update_elo_ratings(
    race_id: Any,
    db: AsyncSession,
    *,
    global_avg_difficulty: float | None = None,
) -> None:
    """Compute and persist ELO changes for a finished race. Idempotent.

    Args:
        global_avg_difficulty: Pre-computed global average seed difficulty.
            When provided (e.g. during full recalculation), skips the DB
            query so that all races use the same stable baseline.
    """
    existing = await db.execute(select(EloHistory.id).where(EloHistory.race_id == race_id).limit(1))
    if existing.scalar_one_or_none() is not None:
        return

    race = await db.get(Race, race_id, options=[selectinload(Race.participants)])
    if race is None:
        return

    # Races flagged exclude_from_elo (Daily Seeds, calibration runs, etc.)
    # never affect ratings, even when they are public and finished.
    if race.exclude_from_elo:
        return

    # Private races don't affect ELO (not verifiable by the community)
    if not race.is_public:
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
        user = users_by_id[p["user_id"]]
        p["elo"] = user.elo_rating
        p["elo_races"] = user.elo_races

    deltas = compute_elo_deltas(players)

    # --- Field strength weighting ---
    player_elos = {p["user_id"]: p["elo"] for p in players}
    deltas = apply_field_strength_weight(deltas, player_elos)

    # --- Zero-sum enforcement ---
    # The asymmetric confidence weighting (established players shielded from
    # provisionals) and adaptive K factor create a systematic leak: when
    # established players beat provisionals, less positive ELO is awarded
    # than negative ELO is removed. Redistribute the excess proportionally
    # to each player's absolute delta so that players with zero delta
    # (fully shielded) stay unaffected.
    total = sum(deltas.values())
    abs_total = sum(abs(d) for d in deltas.values())
    if abs_total > 0 and abs(total) > 1e-10:
        for uid in deltas:
            deltas[uid] -= total * abs(deltas[uid]) / abs_total

    # --- Difficulty injection ---
    # Average over seeds actually used in finished public races. We join
    # through Race.seed_id rather than filtering by SeedStatus because
    # pool rotation marks consumed seeds as DISCARDED.
    seed = await db.get(Seed, race.seed_id) if race.seed_id else None
    if seed and seed.difficulty_score > 0:
        if global_avg_difficulty is not None:
            global_avg = global_avg_difficulty
        else:
            avg_result = await db.execute(
                select(func.avg(Seed.difficulty_score)).where(
                    Seed.difficulty_score > 0,
                    Seed.id.in_(
                        select(Race.seed_id).where(
                            Race.is_public.is_(True),
                            Race.exclude_from_elo.is_(False),
                            Race.status == RaceStatus.FINISHED,
                            Race.seed_id.is_not(None),
                        )
                    ),
                )
            )
            global_avg = avg_result.scalar() or seed.difficulty_score
        difficulty_factor = seed.difficulty_score / global_avg
        deltas = apply_difficulty_bonus(deltas, difficulty_factor)

    # Winner floor: 1st place never loses ELO
    finishers = [p for p in players if p["finished"]]
    if finishers:
        winner = min(finishers, key=lambda p: p["igt_ms"])
        winner_id = winner["user_id"]
        if deltas[winner_id] < 0:
            deltas[winner_id] = 0.0

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
    """Clear all ELO/trait data and replay from scratch."""
    from speedfog_racing.services.seed_difficulty import backfill_difficulty_scores

    await backfill_difficulty_scores(db)

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
                .where(
                    Race.status == RaceStatus.FINISHED,
                    Race.exclude_from_elo.is_(False),
                )
                .order_by(Race.started_at.asc())
            )
        )
        .scalars()
        .all()
    )

    # Pre-compute global average seed difficulty across all finished public
    # races so every replayed race uses the same stable baseline, avoiding
    # temporal distortion from an evolving rolling average.
    avg_result = await db.execute(
        select(func.avg(Seed.difficulty_score)).where(
            Seed.difficulty_score > 0,
            Seed.id.in_(
                select(Race.seed_id).where(
                    Race.is_public.is_(True),
                    Race.exclude_from_elo.is_(False),
                    Race.status == RaceStatus.FINISHED,
                    Race.seed_id.is_not(None),
                )
            ),
        )
    )
    global_avg_diff = avg_result.scalar()

    for race_id in race_ids:
        await update_elo_ratings(race_id, db, global_avg_difficulty=global_avg_diff)
        await update_player_traits(race_id, db)

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
