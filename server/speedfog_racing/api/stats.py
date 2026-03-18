"""Stats API routes: leaderboard, zones, bosses, player profiles."""

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.database import get_db
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
from speedfog_racing.schemas import (
    BossStatEntry,
    BossStatsResponse,
    CommunityStats,
    LeaderboardPlayer,
    LeaderboardResponse,
    PlayerProfilesResponse,
    TraitPlayerEntry,
    ZoneStatEntry,
    ZoneStatsResponse,
    ZoneVisitEntry,
)

router = APIRouter()

DUNGEON_NODE_TYPES = {"legacy_dungeon", "mini_dungeon"}
BOSS_NODE_TYPES = {"boss_arena", "major_boss", "final_boss"}


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(db: AsyncSession = Depends(get_db)) -> LeaderboardResponse:
    """ELO leaderboard with community stats."""
    # Fetch all users who have raced
    users_result = await db.execute(
        select(User).where(User.elo_races > 0).order_by(User.elo_rating.desc())
    )
    users = users_result.scalars().all()

    # Compute wins/losses for each user from finished races
    # Win = 1st place (lowest igt_ms, ties broken by fewer deaths)
    wins_by_user: dict[Any, int] = {}
    losses_by_user: dict[Any, int] = {}

    finished_races_result = await db.execute(
        select(Race)
        .where(Race.status == RaceStatus.FINISHED)
        .options(selectinload(Race.participants))
    )
    finished_races = finished_races_result.scalars().all()

    for race in finished_races:
        finishers = [p for p in race.participants if p.status == ParticipantStatus.FINISHED]
        if len(finishers) < 2:
            continue
        sorted_finishers = sorted(finishers, key=lambda p: (p.igt_ms, p.death_count))
        winner_id = sorted_finishers[0].user_id
        for p in finishers:
            uid = p.user_id
            if uid == winner_id:
                wins_by_user[uid] = wins_by_user.get(uid, 0) + 1
            else:
                losses_by_user[uid] = losses_by_user.get(uid, 0) + 1

    # Compute trend deltas (sum of last 3 EloHistory entries per user)
    user_ids = [u.id for u in users]
    trends: dict[Any, int] = {}
    if user_ids:
        # Fetch last 3 deltas per user using a subquery approach
        for uid in user_ids:
            recent = (
                (
                    await db.execute(
                        select(EloHistory.delta)
                        .where(EloHistory.user_id == uid)
                        .order_by(EloHistory.created_at.desc())
                        .limit(3)
                    )
                )
                .scalars()
                .all()
            )
            trends[uid] = round(sum(recent))

    players = []
    for u in users:
        players.append(
            LeaderboardPlayer(
                twitch_username=u.twitch_username,
                twitch_display_name=u.twitch_display_name,
                twitch_avatar_url=u.twitch_avatar_url,
                elo_rating=round(u.elo_rating),
                elo_races=u.elo_races,
                wins=wins_by_user.get(u.id, 0),
                losses=losses_by_user.get(u.id, 0),
                trend_delta=trends.get(u.id, 0),
                provisional=u.elo_races < 3,
            )
        )

    # Community stats
    total_races = (
        await db.execute(
            select(func.count()).select_from(Race).where(Race.status == RaceStatus.FINISHED)
        )
    ).scalar() or 0

    cutoff = datetime.now(UTC) - timedelta(days=30)
    active_players = (
        await db.execute(
            select(func.count(func.distinct(Participant.user_id)))
            .select_from(Participant)
            .join(Race, Participant.race_id == Race.id)
            .where(
                Race.status == RaceStatus.FINISHED,
                Race.started_at >= cutoff,
            )
        )
    ).scalar() or 0

    total_deaths = (
        await db.execute(
            select(func.sum(Participant.death_count))
            .select_from(Participant)
            .where(Participant.status == ParticipantStatus.FINISHED)
        )
    ).scalar() or 0

    total_igt_ms = (
        await db.execute(
            select(func.sum(Participant.igt_ms))
            .select_from(Participant)
            .where(Participant.status == ParticipantStatus.FINISHED)
        )
    ).scalar() or 0

    hours_raced = round(total_igt_ms / 3_600_000, 1)

    community = CommunityStats(
        total_races=total_races,
        active_players=active_players,
        total_deaths=int(total_deaths),
        hours_raced=hours_raced,
    )

    return LeaderboardResponse(players=players, community=community)


def _aggregate_zone_stats(
    participants: Sequence[Any],
    seeds_by_id: dict[Any, Any],
    node_types: set[str],
) -> dict[str, dict[str, Any]]:
    """Aggregate death and visit counts per display_name from zone_history.

    Groups by display_name so that the same zone across different seeds is counted together.
    visit_rate denominator is the number of unique races where the zone was visited.
    """
    zone_deaths: dict[str, int] = {}
    zone_visits: dict[str, int] = {}
    zone_race_ids: dict[str, set[Any]] = {}
    zone_info: dict[str, dict[str, str]] = {}

    for participant in participants:
        history = participant.zone_history or []
        seed = seeds_by_id.get(participant.race.seed_id) if participant.race else None
        if seed is None:
            continue
        nodes: dict[str, Any] = seed.graph_json.get("nodes", {})
        race_id = participant.race_id

        for entry in history:
            nid = entry.get("node_id", "")
            if not nid:
                continue
            node_meta = nodes.get(nid, {})
            node_type = node_meta.get("type", "")
            if node_type not in node_types:
                continue
            display_name = node_meta.get("display_name", nid)
            deaths = entry.get("deaths", 0)
            zone_deaths[display_name] = zone_deaths.get(display_name, 0) + deaths
            zone_visits[display_name] = zone_visits.get(display_name, 0) + 1
            zone_race_ids.setdefault(display_name, set()).add(race_id)
            if display_name not in zone_info:
                zone_info[display_name] = {
                    "display_name": display_name,
                    "type": node_type,
                }

    return {
        display_name: {
            "display_name": display_name,
            "type": zone_info[display_name]["type"],
            "total_deaths": zone_deaths[display_name],
            "visits": zone_visits[display_name],
            "race_count": len(zone_race_ids[display_name]),
        }
        for display_name in zone_info
    }


@router.get("/zones", response_model=ZoneStatsResponse)
async def get_zone_stats(
    pool: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> ZoneStatsResponse:
    """Zone analytics: deadliest dungeons and most visited nodes."""
    query = (
        select(Participant)
        .where(Participant.status == ParticipantStatus.FINISHED)
        .options(
            selectinload(Participant.race).selectinload(Race.seed),
        )
    )
    if pool is not None:
        query = (
            query.join(Race, Participant.race_id == Race.id)
            .join(Seed, Race.seed_id == Seed.id)
            .where(Seed.pool_name == pool)
        )

    participants = (await db.execute(query)).scalars().all()

    seeds_by_id: dict[Any, Any] = {}
    total_race_ids: set[Any] = set()
    for p in participants:
        if p.race and p.race.seed:
            seeds_by_id[p.race.seed_id] = p.race.seed
        if p.race_id:
            total_race_ids.add(p.race_id)

    total_races = len(total_race_ids)

    node_data = _aggregate_zone_stats(participants, seeds_by_id, DUNGEON_NODE_TYPES)

    # Deadliest: by total_deaths desc
    deadliest_nodes = sorted(node_data.values(), key=lambda n: n["total_deaths"], reverse=True)[:10]
    deadliest = [
        ZoneStatEntry(
            display_name=n["display_name"],
            type=n["type"],
            total_deaths=n["total_deaths"],
            avg_deaths_per_visit=round(n["total_deaths"] / n["visits"], 2)
            if n["visits"] > 0
            else 0.0,
        )
        for n in deadliest_nodes
    ]

    # Most visited: by visit_rate desc (races where zone was visited / total races)
    most_visited_nodes = sorted(
        node_data.values(),
        key=lambda n: n["race_count"],
        reverse=True,
    )[:10]
    most_visited = [
        ZoneVisitEntry(
            display_name=n["display_name"],
            type=n["type"],
            visit_rate=round(n["race_count"] / total_races, 3) if total_races > 0 else 0.0,
            total_visits=n["visits"],
        )
        for n in most_visited_nodes
    ]

    return ZoneStatsResponse(deadliest=deadliest, most_visited=most_visited)


@router.get("/bosses", response_model=BossStatsResponse)
async def get_boss_stats(
    pool: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> BossStatsResponse:
    """Boss encounter stats."""
    query = (
        select(Participant)
        .where(Participant.status == ParticipantStatus.FINISHED)
        .options(
            selectinload(Participant.race).selectinload(Race.seed),
        )
    )
    if pool is not None:
        query = (
            query.join(Race, Participant.race_id == Race.id)
            .join(Seed, Race.seed_id == Seed.id)
            .where(Seed.pool_name == pool)
        )

    participants = (await db.execute(query)).scalars().all()

    seeds_by_id: dict[Any, Any] = {}
    for p in participants:
        if p.race and p.race.seed:
            seeds_by_id[p.race.seed_id] = p.race.seed

    # Aggregate per boss node: deaths list, time_ms list, encounter count
    boss_deaths: dict[str, list[int]] = {}
    boss_times: dict[str, list[int]] = {}
    boss_info: dict[str, dict[str, str]] = {}

    for participant in participants:
        history = participant.zone_history or []
        seed = seeds_by_id.get(participant.race.seed_id) if participant.race else None
        if seed is None:
            continue
        nodes: dict[str, Any] = seed.graph_json.get("nodes", {})

        for entry in history:
            nid = entry.get("node_id", "")
            if not nid:
                continue
            node_meta = nodes.get(nid, {})
            node_type = node_meta.get("type", "")
            if node_type not in BOSS_NODE_TYPES:
                continue
            deaths = entry.get("deaths", 0)
            time_ms = entry.get("time_ms", 0) or 0
            boss_deaths.setdefault(nid, []).append(deaths)
            boss_times.setdefault(nid, []).append(time_ms)
            if nid not in boss_info:
                boss_info[nid] = {
                    "display_name": node_meta.get("display_name", nid),
                    "type": node_type,
                }

    boss_entries = []
    for nid, info in boss_info.items():
        deaths_list = boss_deaths[nid]
        times_list = boss_times[nid]
        boss_entries.append(
            BossStatEntry(
                display_name=info["display_name"],
                type=info["type"],
                encounters=len(deaths_list),
                avg_deaths=round(sum(deaths_list) / len(deaths_list), 2) if deaths_list else 0.0,
                max_deaths=max(deaths_list) if deaths_list else 0,
                avg_time_ms=round(sum(times_list) / len(times_list)) if times_list else 0,
            )
        )

    boss_entries.sort(key=lambda b: b.avg_deaths, reverse=True)

    return BossStatsResponse(bosses=boss_entries)


@router.get("/players", response_model=PlayerProfilesResponse)
async def get_player_profiles(db: AsyncSession = Depends(get_db)) -> PlayerProfilesResponse:
    """Player profiles grouped by dominant trait, top 10 per trait."""
    rows_result = await db.execute(
        select(PlayerTraitScores, User)
        .join(User, PlayerTraitScores.user_id == User.id)
        .where(PlayerTraitScores.dominant_trait.isnot(None))
    )
    rows = rows_result.all()

    # Group by dominant_trait
    by_trait: dict[str, list[tuple[PlayerTraitScores, User]]] = {}
    for scores, user in rows:
        trait = scores.dominant_trait
        if trait:
            by_trait.setdefault(trait, []).append((scores, user))

    profiles: dict[str, list[TraitPlayerEntry]] = {}
    for trait, trait_rows in by_trait.items():
        # Sort by the trait score descending, take top 10
        trait_rows_sorted = sorted(trait_rows, key=lambda r: getattr(r[0], trait, 0), reverse=True)[
            :10
        ]
        profiles[trait] = [
            TraitPlayerEntry(
                twitch_username=user.twitch_username,
                twitch_display_name=user.twitch_display_name,
                twitch_avatar_url=user.twitch_avatar_url,
                score=getattr(scores, trait, 0),
                elo_rating=round(user.elo_rating),
            )
            for scores, user in trait_rows_sorted
        ]

    return PlayerProfilesResponse(profiles=profiles)
