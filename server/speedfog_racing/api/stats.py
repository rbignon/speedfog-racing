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
    ZoneBacktrackEntry,
    ZoneStatEntry,
    ZoneStatsResponse,
    ZoneTimeEntry,
)

router = APIRouter()

DUNGEON_NODE_TYPES = {"legacy_dungeon", "mini_dungeon"}
BOSS_NODE_TYPES = {"major_boss", "final_boss"}


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(db: AsyncSession = Depends(get_db)) -> LeaderboardResponse:
    """ELO leaderboard with community stats."""
    # Fetch users with at least 3 rated races (non-provisional only)
    users_result = await db.execute(
        select(User).where(User.elo_races >= 3).order_by(User.elo_rating.desc())
    )
    users = users_result.scalars().all()

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
                trend_delta=trends.get(u.id, 0),
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


def _resolve_node_display(
    seeds_by_id: dict[Any, Any],
) -> dict[str, tuple[str, str]]:
    """Build node_id -> (display_name, type) from the most recent seed.

    When the same node_id appears in multiple seeds with different display_names
    or types (due to clusters.json evolution), the most recent seed wins.
    """
    node_display: dict[str, tuple[str, str]] = {}
    node_seed_date: dict[str, Any] = {}

    for seed in seeds_by_id.values():
        created = seed.created_at
        nodes: dict[str, Any] = seed.graph_json.get("nodes", {})
        for nid, meta in nodes.items():
            prev_date = node_seed_date.get(nid)
            if prev_date is None or created > prev_date:
                node_seed_date[nid] = created
                full_name = meta.get("display_name", nid)
                short_name = full_name.rsplit(" - ", 1)[-1]
                node_display[nid] = (short_name, meta.get("type", ""))
    return node_display


def _aggregate_zone_stats(
    participants: Sequence[Any],
    seeds_by_id: dict[Any, Any],
    node_types: set[str],
    node_display: dict[str, tuple[str, str]],
) -> dict[str, dict[str, Any]]:
    """Aggregate zone stats per cluster id (node_id) from zone_history.

    Groups by node_id so that the same cluster across different seeds is counted
    together regardless of display_name changes. Filters and resolves display_name
    and type from node_display (most recent seed).
    """
    zone_deaths: dict[str, int] = {}
    zone_visits: dict[str, int] = {}
    zone_race_ids: dict[str, set[Any]] = {}
    zone_backtracks: dict[str, int] = {}
    zone_times: dict[str, list[int]] = {}
    seen_nids: set[str] = set()

    for participant in participants:
        history = participant.zone_history or []
        seed = seeds_by_id.get(participant.race.seed_id) if participant.race else None
        if seed is None:
            continue
        nodes: dict[str, Any] = seed.graph_json.get("nodes", {})
        race_id = participant.race_id

        # Track visited node_ids per participant for backtrack detection
        visited_nids: set[str] = set()

        for idx, entry in enumerate(history):
            nid = entry.get("node_id", "")
            if not nid:
                continue
            # Node must exist in this seed's graph
            if nid not in nodes:
                continue
            # Filter by most recent type (not the per-seed type)
            resolved_type = node_display.get(nid, ("", ""))[1]
            if resolved_type not in node_types:
                continue
            deaths = entry.get("deaths", 0)
            zone_deaths[nid] = zone_deaths.get(nid, 0) + deaths
            zone_visits[nid] = zone_visits.get(nid, 0) + 1
            zone_race_ids.setdefault(nid, set()).add(race_id)
            seen_nids.add(nid)

            # Backtrack: revisiting a node_id already seen by this participant
            if nid in visited_nids:
                zone_backtracks[nid] = zone_backtracks.get(nid, 0) + 1
            visited_nids.add(nid)

            # Time: difference between this entry's igt_ms and next entry's igt_ms
            current_igt = entry.get("igt_ms", 0)
            if idx + 1 < len(history):
                next_igt = history[idx + 1].get("igt_ms", 0)
                if current_igt > 0 and next_igt > current_igt:
                    zone_times.setdefault(nid, []).append(next_igt - current_igt)

    # Merge clusters that share the same display_name (e.g. Godskin Duo
    # has two cluster ids but should appear as one entry in stats)
    merged: dict[str, dict[str, Any]] = {}
    for nid in seen_nids:
        display_name = node_display.get(nid, (nid, ""))[0]
        node_type = node_display.get(nid, ("", ""))[1]
        if display_name in merged:
            m = merged[display_name]
            m["total_deaths"] += zone_deaths[nid]
            m["visits"] += zone_visits[nid]
            m["race_ids"].update(zone_race_ids[nid])
            m["backtrack_count"] += zone_backtracks.get(nid, 0)
            m["times"].extend(zone_times.get(nid, []))
        else:
            merged[display_name] = {
                "display_name": display_name,
                "type": node_type,
                "total_deaths": zone_deaths[nid],
                "visits": zone_visits[nid],
                "race_ids": set(zone_race_ids[nid]),
                "backtrack_count": zone_backtracks.get(nid, 0),
                "times": list(zone_times.get(nid, [])),
            }

    return {
        name: {
            "display_name": name,
            "type": data["type"],
            "total_deaths": data["total_deaths"],
            "visits": data["visits"],
            "race_count": len(data["race_ids"]),
            "backtrack_count": data["backtrack_count"],
            "times": data["times"],
        }
        for name, data in merged.items()
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
    for p in participants:
        if p.race and p.race.seed:
            seeds_by_id[p.race.seed_id] = p.race.seed

    node_display = _resolve_node_display(seeds_by_id)
    node_data = _aggregate_zone_stats(participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display)

    # Deadliest: by total_deaths desc
    deadliest_nodes = sorted(node_data.values(), key=lambda n: n["total_deaths"], reverse=True)[:5]
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

    # Most backtracked: zones players revisit most often
    backtracked_nodes = sorted(
        [n for n in node_data.values() if n["backtrack_count"] > 0],
        key=lambda n: n["backtrack_count"],
        reverse=True,
    )[:5]
    most_backtracked = [
        ZoneBacktrackEntry(
            display_name=n["display_name"],
            type=n["type"],
            backtrack_count=n["backtrack_count"],
            avg_backtracks_per_race=round(n["backtrack_count"] / n["race_count"], 2)
            if n["race_count"] > 0
            else 0.0,
        )
        for n in backtracked_nodes
    ]

    # Slowest: zones with highest average traversal time
    slowest_nodes = sorted(
        [n for n in node_data.values() if n["times"]],
        key=lambda n: sum(n["times"]) / len(n["times"]),
        reverse=True,
    )[:5]
    slowest = [
        ZoneTimeEntry(
            display_name=n["display_name"],
            type=n["type"],
            avg_time_ms=round(sum(n["times"]) / len(n["times"])),
            visits=len(n["times"]),
        )
        for n in slowest_nodes
    ]

    # Fastest: zones with lowest average traversal time (min 3 visits to avoid outliers)
    fastest_nodes = sorted(
        [n for n in node_data.values() if len(n["times"]) >= 3],
        key=lambda n: sum(n["times"]) / len(n["times"]),
    )[:5]
    fastest = [
        ZoneTimeEntry(
            display_name=n["display_name"],
            type=n["type"],
            avg_time_ms=round(sum(n["times"]) / len(n["times"])),
            visits=len(n["times"]),
        )
        for n in fastest_nodes
    ]

    return ZoneStatsResponse(
        deadliest=deadliest,
        most_backtracked=most_backtracked,
        slowest=slowest,
        fastest=fastest,
    )


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

    node_display = _resolve_node_display(seeds_by_id)

    # Aggregate per cluster id (node_id): deaths list, time_ms list
    boss_deaths: dict[str, list[int]] = {}
    boss_times: dict[str, list[int]] = {}

    for participant in participants:
        history = participant.zone_history or []
        seed = seeds_by_id.get(participant.race.seed_id) if participant.race else None
        if seed is None:
            continue
        nodes: dict[str, Any] = seed.graph_json.get("nodes", {})

        for idx, entry in enumerate(history):
            nid = entry.get("node_id", "")
            if not nid:
                continue
            if nid not in nodes:
                continue
            # Filter by most recent type
            resolved_type = node_display.get(nid, ("", ""))[1]
            if resolved_type not in BOSS_NODE_TYPES:
                continue
            deaths = entry.get("deaths", 0)

            # Time in zone = next entry's igt_ms - current entry's igt_ms
            # For the last entry, use participant's final igt_ms as end time
            current_igt = entry.get("igt_ms", 0) or 0
            is_last = idx >= len(history) - 1
            if is_last:
                next_igt = participant.igt_ms or 0
            else:
                next_igt = history[idx + 1].get("igt_ms", 0) or 0
            time_ms = next_igt - current_igt if current_igt > 0 and next_igt > current_igt else None

            boss_deaths.setdefault(nid, []).append(deaths)
            if time_ms is not None:
                boss_times.setdefault(nid, []).append(time_ms)

    # Merge clusters that share the same display_name (e.g. Godskin Duo
    # has two cluster ids but should appear as one entry)
    merged_deaths: dict[str, list[int]] = {}
    merged_times: dict[str, list[int]] = {}
    merged_type: dict[str, str] = {}
    for nid, deaths_list in boss_deaths.items():
        display_name, node_type = node_display.get(nid, (nid, "major_boss"))
        merged_deaths.setdefault(display_name, []).extend(deaths_list)
        merged_times.setdefault(display_name, []).extend(boss_times.get(nid, []))
        merged_type.setdefault(display_name, node_type)

    boss_entries = []
    for display_name, deaths_list in merged_deaths.items():
        times_list = merged_times.get(display_name, [])
        boss_entries.append(
            BossStatEntry(
                display_name=display_name,
                type=merged_type[display_name],
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
        .where(PlayerTraitScores.dominant_trait.isnot(None), User.elo_races >= 3)
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
