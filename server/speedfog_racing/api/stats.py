"""Stats API routes: leaderboard, zones, bosses, player profiles."""

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import mean
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, or_, select
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
    WeaponComboStat,
    WeaponStatsResponse,
    ZoneBacktrackEntry,
    ZoneDetailResponse,
    ZoneIndexEntry,
    ZoneIndexResponse,
    ZoneStatEntry,
    ZoneStatsResponse,
    ZoneTimeEntry,
)

router = APIRouter()

DUNGEON_NODE_TYPES = {"legacy_dungeon", "mini_dungeon"}
# Only major_boss and final_boss for the public boss stats page.
# boss_arena is intentionally excluded here (minor encounters), but IS included
# in stats_service.py's BOSS_NODE_TYPES for trait scoring (Boss Slayer).
BOSS_NODE_TYPES = {"major_boss", "final_boss"}


@router.get("/leaderboard", response_model=LeaderboardResponse)
async def get_leaderboard(db: AsyncSession = Depends(get_db)) -> LeaderboardResponse:
    """ELO leaderboard with community stats."""
    # Fetch users with at least 3 rated races, sorted strictly by ELO rating.
    users_result = await db.execute(
        select(User).where(User.elo_races >= 3).order_by(User.elo_rating.desc())
    )
    users = users_result.scalars().all()

    # Compute trend deltas (sum of last 3 EloHistory entries per user)
    user_ids = [u.id for u in users]
    trends: dict[Any, int] = {}
    if user_ids:
        # Batch fetch all recent EloHistory for qualified users in one query,
        # then group in Python. Replaces the N+1 pattern (one query per user).
        all_history = (
            await db.execute(
                select(EloHistory.user_id, EloHistory.delta)
                .where(EloHistory.user_id.in_(user_ids))
                .order_by(EloHistory.user_id, EloHistory.created_at.desc())
            )
        ).all()

        # Accumulate last 3 deltas per user
        delta_counts: dict[Any, int] = {}
        for uid, delta in all_history:
            count = delta_counts.get(uid, 0)
            if count < 3:
                trends[uid] = trends.get(uid, 0) + round(delta)
                delta_counts[uid] = count + 1

    # Compute Strength of Schedule: average ELO of opponents per user.
    # Joins on EloHistory, so races without ELO entries (solo finishes,
    # races that never had update_elo_ratings run) are naturally excluded.
    sos: dict[Any, int] = {}
    if user_ids:
        user_races_sq = (
            select(Participant.race_id, Participant.user_id)
            .where(
                Participant.user_id.in_(user_ids),
                Participant.status.in_([ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED]),
                Participant.igt_ms > 0,
            )
            .subquery()
        )

        opp_elos = (
            await db.execute(
                select(
                    user_races_sq.c.user_id,
                    func.avg(EloHistory.elo_before),
                )
                .join(
                    EloHistory,
                    (EloHistory.race_id == user_races_sq.c.race_id)
                    & (EloHistory.user_id != user_races_sq.c.user_id),
                )
                .group_by(user_races_sq.c.user_id)
            )
        ).all()

        for uid, avg_opp in opp_elos:
            if avg_opp is not None:
                sos[uid] = round(avg_opp)

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
                avg_opponent_elo=sos.get(u.id),
                equipped_badge_id=u.equipped_badge_id,
                equipped_name_template_id=u.equipped_name_template_id,
            )
        )

    # Community stats (public races only).
    # Daily Seeds (exclude_from_elo=True) are intentionally included here:
    # community KPIs describe total racing activity, not only ELO-rated runs.
    public_finished = (Race.status == RaceStatus.FINISHED) & (Race.is_public == True)  # noqa: E712

    total_races = (
        await db.execute(select(func.count()).select_from(Race).where(public_finished))
    ).scalar() or 0

    cutoff = datetime.now(UTC) - timedelta(days=30)
    active_players = (
        await db.execute(
            select(func.count(func.distinct(Participant.user_id)))
            .select_from(Participant)
            .join(Race, Participant.race_id == Race.id)
            .where(
                public_finished,
                Race.started_at >= cutoff,
            )
        )
    ).scalar() or 0

    participated_filter = or_(
        Participant.status == ParticipantStatus.FINISHED,
        (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
    )

    total_deaths = (
        await db.execute(
            select(func.sum(Participant.death_count))
            .select_from(Participant)
            .join(Race, Participant.race_id == Race.id)
            .where(participated_filter, public_finished)
        )
    ).scalar() or 0

    total_igt_ms = (
        await db.execute(
            select(func.sum(Participant.igt_ms))
            .select_from(Participant)
            .join(Race, Participant.race_id == Race.id)
            .where(participated_filter, public_finished)
        )
    ).scalar() or 0

    hours_raced = round(total_igt_ms / 3_600_000, 1)

    community = CommunityStats(
        total_races=total_races,
        active_players=active_players,
        ranked_players=len(players),
        total_deaths=int(total_deaths),
        hours_raced=hours_raced,
    )

    return LeaderboardResponse(players=players, community=community)


@dataclass(frozen=True)
class NodeDisplay:
    """Resolved per-node naming/type/zones from the most recent seed containing it.

    ``short_name`` is the last " - " segment (area prefix stripped), used by
    the top-5 panels. ``full_name`` is the unmodified display_name, used by
    the zone codex index/detail and as the merge key in
    ``_aggregate_zone_stats`` (see there for why merging must use the full
    name).
    """

    short_name: str
    full_name: str
    type: str
    # A tuple, not a list: NodeDisplay instances live forever in the shared
    # seed projection cache, so their contents must be structurally immutable.
    zones: tuple[str, ...]


@dataclass(frozen=True)
class SeedNodes:
    """Cached projection of one seed's graph nodes.

    The zone stats endpoints only need node membership and per-node display
    metadata, a few KB out of a graph_json that can weigh hundreds of KB.
    ``created_at`` orders seeds for most-recent display resolution.
    """

    created_at: datetime
    nodes: dict[str, NodeDisplay]


# Seed graphs are immutable once the seed is consumed, so projections are
# cached in-process forever: no TTL, no invalidation. Entries are a few KB
# each and only accumulate at the pace new seeds get raced.
_seed_nodes_cache: dict[Any, SeedNodes] = {}


def _project_seed_nodes(created_at: datetime, graph_json: dict[str, Any]) -> SeedNodes:
    """Extract the SeedNodes projection from a raw graph_json."""
    nodes: dict[str, NodeDisplay] = {}
    for nid, meta in graph_json.get("nodes", {}).items():
        full_name = meta.get("display_name", nid)
        short_name = full_name.rsplit(" - ", 1)[-1]
        nodes[nid] = NodeDisplay(
            short_name=short_name,
            full_name=full_name,
            type=meta.get("type", ""),
            zones=tuple(meta.get("zones", [])),
        )
    return SeedNodes(created_at=created_at, nodes=nodes)


def _resolve_node_display(seed_nodes_by_id: dict[Any, SeedNodes]) -> dict[str, NodeDisplay]:
    """Build node_id -> NodeDisplay from the most recent seed.

    Node IDs are cluster IDs from SpeedFog's clusters.json. The same cluster_id
    always refers to the same physical location, but display_names, types, and
    zone composition can change across seeds if clusters.json was updated
    between seed generations (e.g. display_name typo fixed, or a cluster
    reclassified from major_boss to legacy_dungeon). Using the most recent seed
    ensures stats show current names. ``zones`` is the cluster's own fine-grained
    zone id list (fog.txt identifiers), used for skip/tip content matching;
    graphs that predate the field resolve to an empty list.
    """
    node_display: dict[str, NodeDisplay] = {}
    node_seed_date: dict[str, Any] = {}

    for seed_nodes in seed_nodes_by_id.values():
        created = seed_nodes.created_at
        for nid, display in seed_nodes.nodes.items():
            prev_date = node_seed_date.get(nid)
            if prev_date is None or created > prev_date:
                node_seed_date[nid] = created
                node_display[nid] = display
    return node_display


def _aggregate_zone_stats(
    participants: Sequence[Any],
    seed_nodes_by_id: dict[Any, SeedNodes],
    node_types: set[str],
    node_display: dict[str, NodeDisplay],
) -> dict[str, dict[str, Any]]:
    """Aggregate zone stats per cluster id (node_id) from zone_history.

    Groups by node_id so that the same cluster across different seeds is counted
    together regardless of display_name changes. Filters and resolves display_name
    and type from node_display (most recent seed). Merging (see below) is keyed
    on the FULL display_name, not the short one: two different physical
    locations can share a last " - " segment (e.g. "Foo Ruins - East" and
    "Bar Caves - East"), and merging on the short name would wrongly combine
    their stats. Each merged entry carries both "display_name" (full, used by
    the index/detail endpoints) and "short_name" (used by the top-5 panels),
    and its "zones" is the sorted union of all its contributing node_ids' own
    zones lists, since a merge can combine cluster variants with different
    zone compositions (asymmetric drop connectivity).
    """
    zone_deaths: dict[str, int] = {}
    zone_visits: dict[str, int] = {}
    zone_race_ids: dict[str, set[Any]] = {}
    zone_backtracks: dict[str, int] = {}
    zone_times: dict[str, list[int]] = {}
    seen_nids: set[str] = set()

    for participant in participants:
        history = participant.zone_history or []
        seed_nodes = seed_nodes_by_id.get(participant.seed_id)
        if seed_nodes is None:
            continue
        nodes = seed_nodes.nodes
        race_id = participant.race_id

        for idx, entry in enumerate(history):
            nid = entry.get("node_id", "")
            if not nid:
                continue
            # Node must exist in this seed's graph
            if nid not in nodes:
                continue
            # Filter by most recent type (not the per-seed type)
            resolved_info = node_display.get(nid)
            if resolved_info is None or resolved_info.type not in node_types:
                continue
            deaths = entry.get("deaths", 0)
            zone_deaths[nid] = zone_deaths.get(nid, 0) + deaths
            zone_visits[nid] = zone_visits.get(nid, 0) + 1
            zone_race_ids.setdefault(nid, set()).add(race_id)
            seen_nids.add(nid)

            # Backtrack: the player turned away from this zone to take another
            # path. Its entry immediately precedes a type "backtrack" entry
            # (warp landings recorded on death/teleport/quit-out), except when
            # this entry is itself such a landing (a warp chain credits only
            # the zone the player originally left) or when the chain ends with
            # the player back in this zone (death runback, not a path change).
            if (
                entry.get("type", "fog") != "backtrack"
                and idx + 1 < len(history)
                and history[idx + 1].get("type") == "backtrack"
            ):
                # Walk the warp chain plus the first entry after it: if the
                # player ends up back in this zone, they did not change path.
                returned = False
                j = idx + 1
                while j < len(history) and history[j].get("type") == "backtrack":
                    returned = returned or history[j].get("node_id") == nid
                    j += 1
                if j < len(history):
                    returned = returned or history[j].get("node_id") == nid
                if not returned:
                    zone_backtracks[nid] = zone_backtracks.get(nid, 0) + 1

            # Time: difference between this entry's igt_ms and next entry's igt_ms
            current_igt = entry.get("igt_ms", 0)
            if idx + 1 < len(history):
                next_igt = history[idx + 1].get("igt_ms", 0)
                if current_igt > 0 and next_igt > current_igt:
                    zone_times.setdefault(nid, []).append(next_igt - current_igt)
            else:
                # Last zone: use participant's final IGT as the "next" timestamp
                final_igt = participant.igt_ms or 0
                if current_igt > 0 and final_igt > current_igt:
                    zone_times.setdefault(nid, []).append(final_igt - current_igt)

        # Count abandon as backtrack for the participant's last zone (they
        # renounced there), but only on a first visit.
        if participant.status == ParticipantStatus.ABANDONED and history:
            last_nid = history[-1].get("node_id", "")
            if last_nid and last_nid in nodes:
                last_info = node_display.get(last_nid)
                is_first_visit = sum(1 for e in history if e.get("node_id") == last_nid) == 1
                if last_info is not None and last_info.type in node_types and is_first_visit:
                    zone_backtracks[last_nid] = zone_backtracks.get(last_nid, 0) + 1

    # Merge clusters sharing the same FULL display_name. This happens when the
    # same physical location produces different cluster_ids due to asymmetric
    # drop connectivity in the zone graph (different entry points yield
    # different reachable zone sets, so different cluster hashes).
    # sorted() makes the representative node_id (first cluster id seen per
    # display_name, stored below) deterministic across runs: seen_nids is a
    # set, and Python's per-process string hash randomization would otherwise
    # let the representative flip on every process restart.
    merged: dict[str, dict[str, Any]] = {}
    for nid in sorted(seen_nids):
        # seen_nids only gains ids that passed the node_types filter above,
        # which requires a node_display entry, so this lookup cannot be None.
        info = node_display[nid]
        if info.full_name in merged:
            m = merged[info.full_name]
            m["total_deaths"] += zone_deaths[nid]
            m["visits"] += zone_visits[nid]
            m["race_ids"].update(zone_race_ids[nid])
            m["backtrack_count"] += zone_backtracks.get(nid, 0)
            m["times"].extend(zone_times.get(nid, []))
            m["zones"].update(info.zones)
        else:
            merged[info.full_name] = {
                "node_id": nid,
                "display_name": info.full_name,
                "short_name": info.short_name,
                "type": info.type,
                "total_deaths": zone_deaths[nid],
                "visits": zone_visits[nid],
                "race_ids": set(zone_race_ids[nid]),
                "backtrack_count": zone_backtracks.get(nid, 0),
                "times": list(zone_times.get(nid, [])),
                "zones": set(info.zones),
            }

    return {
        name: {
            "node_id": data["node_id"],
            "display_name": name,
            "short_name": data["short_name"],
            "type": data["type"],
            "total_deaths": data["total_deaths"],
            "visits": data["visits"],
            "race_count": len(data["race_ids"]),
            "backtrack_count": data["backtrack_count"],
            "times": data["times"],
            "zones": sorted(data["zones"]),
        }
        for name, data in merged.items()
    }


async def _load_zone_stats_inputs(
    pool: str | None, days: int, db: AsyncSession
) -> tuple[Sequence[Any], dict[Any, SeedNodes]]:
    """Shared loader for zone stats endpoints.

    Returns eligible participant rows (FINISHED, or ABANDONED with igt_ms > 0;
    ``race_id``, ``status``, ``igt_ms``, ``zone_history``, ``seed_id``) in
    races started within the last ``days`` days, optionally restricted to
    ``pool``, plus the SeedNodes projections keyed by the seed_ids they raced
    on. Narrow column selects on purpose: full ORM entities with their seeds'
    graph_json cost >1s of hydration per request at ~3400 participants, while
    the stats only consume these five fields plus the cached projections.
    """
    query = (
        select(
            Participant.race_id,
            Participant.status,
            Participant.igt_ms,
            Participant.zone_history,
            Race.seed_id,
        )
        .join(Race, Participant.race_id == Race.id)
        .where(
            or_(
                Participant.status == ParticipantStatus.FINISHED,
                (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
            )
        )
    )
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    query = query.where(Race.started_at >= cutoff)
    if pool is not None:
        query = query.join(Seed, Race.seed_id == Seed.id).where(Seed.pool_name == pool)

    participants = (await db.execute(query)).all()

    # Races can have a NULL seed_id; None is never cacheable and would force
    # a pointless seed query on every request if left in the set.
    seed_ids = {row.seed_id for row in participants if row.seed_id is not None}
    missing = [sid for sid in seed_ids if sid not in _seed_nodes_cache]
    if missing:
        seed_rows = (
            await db.execute(
                select(Seed.id, Seed.created_at, Seed.graph_json).where(Seed.id.in_(missing))
            )
        ).all()
        for sid, created_at, graph_json in seed_rows:
            _seed_nodes_cache[sid] = _project_seed_nodes(created_at, graph_json)

    seed_nodes_by_id = {sid: _seed_nodes_cache[sid] for sid in seed_ids if sid in _seed_nodes_cache}
    return participants, seed_nodes_by_id


@router.get("/zones", response_model=ZoneStatsResponse)
async def get_zone_stats(
    pool: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
) -> ZoneStatsResponse:
    """Zone analytics: deadliest dungeons and most visited nodes.

    ``days`` restricts the input to races started within the last N days
    (default 30, range 1..3650). The output is capped at 5 entries per
    category (deadliest, backtracked, slowest, fastest). ``display_name`` on
    each entry is the SHORT name (area prefix stripped); the zone codex
    index/detail endpoints serve the full name instead.
    """
    participants, seeds_by_id = await _load_zone_stats_inputs(pool, days, db)

    node_display = _resolve_node_display(seeds_by_id)
    node_data = _aggregate_zone_stats(participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display)

    # Deadliest: by avg_deaths_per_visit desc (rate metric, not biased by popularity)
    deadliest_nodes = sorted(
        [n for n in node_data.values() if n["visits"] > 0],
        key=lambda n: n["total_deaths"] / n["visits"],
        reverse=True,
    )[:5]
    deadliest = [
        ZoneStatEntry(
            node_id=n["node_id"],
            display_name=n["short_name"],
            type=n["type"],
            total_deaths=n["total_deaths"],
            avg_deaths_per_visit=round(n["total_deaths"] / n["visits"], 2)
            if n["visits"] > 0
            else 0.0,
        )
        for n in deadliest_nodes
    ]

    # Most backtracked: by avg_backtracks_per_race desc (rate metric)
    backtracked_nodes = sorted(
        [n for n in node_data.values() if n["backtrack_count"] > 0],
        key=lambda n: n["backtrack_count"] / n["race_count"] if n["race_count"] > 0 else 0,
        reverse=True,
    )[:5]
    most_backtracked = [
        ZoneBacktrackEntry(
            node_id=n["node_id"],
            display_name=n["short_name"],
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
            node_id=n["node_id"],
            display_name=n["short_name"],
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
            node_id=n["node_id"],
            display_name=n["short_name"],
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


@router.get("/zones/index", response_model=ZoneIndexResponse)
async def get_zone_index(
    pool: str | None = Query(default=None),
    days: int = Query(default=90, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
) -> ZoneIndexResponse:
    """All explorable zones with aggregate stats, for the zone codex index.

    ``days`` restricts the input to races started within the last N days
    (default 90, range 1..3650). Unlike ``/zones``, this is not capped at 5
    entries per category: it returns every dungeon-type zone, sorted by
    display_name, for a browsable index. ``display_name`` is the FULL name
    (unlike the top-5 panels on ``/zones``, which use the short one).
    """
    participants, seeds_by_id = await _load_zone_stats_inputs(pool, days, db)
    node_display = _resolve_node_display(seeds_by_id)
    node_data = _aggregate_zone_stats(participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display)
    zones = [
        ZoneIndexEntry(
            node_id=data["node_id"],
            display_name=data["display_name"],
            type=data["type"],
            visits=data["visits"],
            avg_time_ms=round(mean(data["times"])) if data["times"] else 0,
            avg_deaths_per_visit=(
                round(data["total_deaths"] / data["visits"], 2) if data["visits"] else 0.0
            ),
            backtrack_rate=(
                round(data["backtrack_count"] / data["race_count"], 2)
                if data["race_count"]
                else 0.0
            ),
            zones=data["zones"],
        )
        for data in node_data.values()
    ]
    zones.sort(key=lambda z: z.display_name)
    return ZoneIndexResponse(zones=zones)


@router.get("/zones/{node_id}", response_model=ZoneDetailResponse)
async def get_zone_detail(
    node_id: str,
    pool: str | None = Query(default=None),
    days: int = Query(default=90, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
) -> ZoneDetailResponse:
    """Aggregate stats for one explorable zone, for the zone codex detail sheet.

    404s when ``node_id`` is unknown, or when it resolves to a node type
    outside ``DUNGEON_NODE_TYPES`` (e.g. a boss arena). Returns zeroed stats
    (``avg_time_ms=None``, ``visits=0``, ...) when the zone is known but has
    no visits within the ``days`` window. ``display_name`` is the FULL name
    (same as the index, unlike the top-5 panels on ``/zones``).
    """
    participants, seeds_by_id = await _load_zone_stats_inputs(pool, days, db)
    node_display = _resolve_node_display(seeds_by_id)
    info = node_display.get(node_id)
    if info is None:
        raise HTTPException(status_code=404, detail="Unknown zone")
    if info.type not in DUNGEON_NODE_TYPES:
        raise HTTPException(status_code=404, detail="Not an explorable zone")
    node_data = _aggregate_zone_stats(participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display)
    data = node_data.get(info.full_name)
    if data is None:
        return ZoneDetailResponse(
            node_id=node_id,
            display_name=info.full_name,
            type=info.type,
            visits=0,
            race_count=0,
            avg_time_ms=None,
            avg_deaths_per_visit=0.0,
            backtrack_rate=0.0,
            zones=list(info.zones),
        )
    return ZoneDetailResponse(
        # Echo the requested node_id, not data["node_id"] (the merge's
        # representative cluster id): a caller requesting a specific
        # backtrack-merged sibling id must get that same id back, even
        # though the aggregate itself is shared across the merge group.
        # Same for zones: info.zones (the requested id's own composition),
        # not data["zones"] (the merge's union across all siblings).
        node_id=node_id,
        display_name=data["display_name"],
        type=data["type"],
        visits=data["visits"],
        race_count=data["race_count"],
        avg_time_ms=round(mean(data["times"])) if data["times"] else None,
        avg_deaths_per_visit=(
            round(data["total_deaths"] / data["visits"], 2) if data["visits"] else 0.0
        ),
        zones=list(info.zones),
        backtrack_rate=(
            round(data["backtrack_count"] / data["race_count"], 2) if data["race_count"] else 0.0
        ),
    )


@router.get("/bosses", response_model=BossStatsResponse)
async def get_boss_stats(
    pool: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> BossStatsResponse:
    """Boss encounter stats."""
    query = (
        select(Participant)
        .where(
            or_(
                Participant.status == ParticipantStatus.FINISHED,
                (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
            )
        )
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

    # Per participant, collect boss encounter data.
    # Resolve display name per-seed (boss_name > randomized_boss > display_name).
    # back_ratio: on a player's LAST visit to a boss, did they backtrack?
    # avg_deaths / max_deaths: deaths are summed per participant across fight visits,
    # so a player who fights a boss in 50+40 deaths over two visits is counted once
    # with 90 deaths, not as two encounters of 50 and 40.
    # Participants whose only visits are 0-death backtracks (pure transit) are not
    # counted as encounters at all.
    player_deaths: dict[str, list[int]] = {}
    merged_backed: dict[str, list[bool]] = {}
    merged_times: dict[str, list[int]] = {}
    merged_type: dict[str, str] = {}

    for participant in participants:
        history = participant.zone_history or []
        seed = seeds_by_id.get(participant.race.seed_id) if participant.race else None
        if seed is None:
            continue
        nodes: dict[str, Any] = seed.graph_json.get("nodes", {})

        # Collect all visits per boss node_id for this participant
        visits_by_nid: dict[str, list[tuple[int, dict[str, Any]]]] = {}
        for idx, entry in enumerate(history):
            nid = entry.get("node_id", "")
            if not nid or nid not in nodes:
                continue
            if nodes[nid].get("type", "") not in BOSS_NODE_TYPES:
                continue
            visits_by_nid.setdefault(nid, []).append((idx, entry))

        for nid, visits in visits_by_nid.items():
            # Collect deaths from all visits, excluding 0-death backtracks
            # (those don't represent actual combat)
            fight_deaths: list[int] = []
            for visit_idx, visit_entry in visits:
                deaths = visit_entry.get("deaths", 0)
                if deaths == 0 and visit_idx + 1 < len(history):
                    next_nid = history[visit_idx + 1].get("node_id", "")
                    prev_visited: set[str] = set()
                    for prev_entry in history[:visit_idx]:
                        prev_nid = prev_entry.get("node_id", "")
                        if prev_nid:
                            prev_visited.add(prev_nid)
                    if next_nid in prev_visited:
                        continue  # 0-death backtrack, skip
                fight_deaths.append(deaths)

            # Player only passed through the boss arena without fighting: skip
            # entirely so encounters / back_ratio / time aren't inflated.
            if not fight_deaths:
                continue

            last_idx, last_entry = visits[-1]

            # back_ratio: did the player backtrack on their last visit?
            # Check if the node after the last visit was already visited.
            # An abandon at the boss also counts as a back.
            backed_last_visit = False
            if last_idx + 1 < len(history):
                next_nid = history[last_idx + 1].get("node_id", "")
                visited_before: set[str] = set()
                for prev_entry in history[:last_idx]:
                    prev_nid = prev_entry.get("node_id", "")
                    if prev_nid:
                        visited_before.add(prev_nid)
                backed_last_visit = next_nid in visited_before
            elif participant.status == ParticipantStatus.ABANDONED:
                backed_last_visit = True

            # Time: use last visit for time calculation
            current_igt = last_entry.get("igt_ms", 0) or 0
            if last_idx + 1 < len(history):
                next_igt = history[last_idx + 1].get("igt_ms", 0) or 0
            else:
                next_igt = participant.igt_ms or 0
            time_ms = next_igt - current_igt if current_igt > 0 and next_igt > current_igt else None

            # Resolve boss name from this participant's seed
            node_meta = nodes[nid]
            boss_name = (node_meta.get("boss_name") or node_meta.get("display_name", nid)).rsplit(
                " - ", 1
            )[-1]
            node_type = node_meta.get("type", "major_boss")

            player_deaths.setdefault(boss_name, []).append(sum(fight_deaths))
            merged_backed.setdefault(boss_name, []).append(backed_last_visit)
            if time_ms is not None:
                merged_times.setdefault(boss_name, []).append(time_ms)
            merged_type.setdefault(boss_name, node_type)

    boss_entries = []
    for display_name, backed_list in merged_backed.items():
        deaths_per_player = player_deaths.get(display_name, [])
        times = merged_times.get(display_name, [])
        total_encounters = len(backed_list)
        backed_count = sum(backed_list)

        boss_entries.append(
            BossStatEntry(
                display_name=display_name,
                type=merged_type[display_name],
                encounters=total_encounters,
                avg_deaths=(
                    round(sum(deaths_per_player) / len(deaths_per_player), 2)
                    if deaths_per_player
                    else 0.0
                ),
                max_deaths=max(deaths_per_player) if deaths_per_player else 0,
                avg_time_ms=round(sum(times) / len(times)) if times else 0,
                back_ratio=round(backed_count / total_encounters, 2) if total_encounters else 0.0,
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


@router.get("/weapons", response_model=WeaponStatsResponse)
async def get_weapon_stats(
    pool: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
) -> WeaponStatsResponse:
    """Top weapon combos by total ticks across recent public finished races."""
    query = (
        select(Participant)
        .join(Race, Participant.race_id == Race.id)
        .where(
            or_(
                Participant.status == ParticipantStatus.FINISHED,
                (Participant.status == ParticipantStatus.ABANDONED) & (Participant.igt_ms > 0),
            ),
            Race.status == RaceStatus.FINISHED,
            Race.is_public == True,  # noqa: E712
        )
    )
    cutoff = datetime.now(tz=UTC) - timedelta(days=days)
    query = query.where(Race.started_at >= cutoff)
    if pool is not None:
        query = query.join(Seed, Race.seed_id == Seed.id).where(Seed.pool_name == pool)

    participants = (await db.execute(query)).scalars().all()

    totals: dict[tuple[int, ...], int] = {}
    races: dict[tuple[int, ...], set[Any]] = {}
    players: dict[tuple[int, ...], set[Any]] = {}
    user_combo_ticks: dict[Any, dict[tuple[int, ...], int]] = {}

    for p in participants:
        history = p.zone_history or []
        for entry in history:
            combos = entry.get("weapons") or []
            for combo in combos:
                ids = combo.get("ids")
                ticks = combo.get("ticks", 0)
                if not isinstance(ids, list) or not isinstance(ticks, int) or ticks <= 0:
                    continue
                base_ids = tuple(i - (i % 1000) for i in ids)
                totals[base_ids] = totals.get(base_ids, 0) + ticks
                races.setdefault(base_ids, set()).add(p.race_id)
                players.setdefault(base_ids, set()).add(p.user_id)
                per_user = user_combo_ticks.setdefault(p.user_id, {})
                per_user[base_ids] = per_user.get(base_ids, 0) + ticks

    # For each combo, find the user with the most ticks on this combo
    # (regardless of whether it is their personal #1). Ties are broken
    # arbitrarily by insertion order.
    top_user_per_combo: dict[tuple[int, ...], Any] = {}
    top_user_ticks_per_combo: dict[tuple[int, ...], int] = {}
    for user_id, per_user in user_combo_ticks.items():
        for combo_key, ticks in per_user.items():
            if ticks > top_user_ticks_per_combo.get(combo_key, 0):
                top_user_per_combo[combo_key] = user_id
                top_user_ticks_per_combo[combo_key] = ticks

    sorted_keys = sorted(totals, key=lambda k: totals[k], reverse=True)[:20]

    # Batch-fetch user info for the top players present in the top 20.
    top_user_ids = {top_user_per_combo[k] for k in sorted_keys if k in top_user_per_combo}
    users_by_id: dict[Any, User] = {}
    if top_user_ids:
        rows = (await db.execute(select(User).where(User.id.in_(top_user_ids)))).scalars().all()
        users_by_id = {u.id: u for u in rows}

    combos_out: list[WeaponComboStat] = []
    for k in sorted_keys:
        top_uid = top_user_per_combo.get(k)
        top_user = users_by_id.get(top_uid) if top_uid is not None else None
        combos_out.append(
            WeaponComboStat(
                ids=list(k),
                total_ticks=totals[k],
                race_count=len(races[k]),
                player_count=len(players[k]),
                top_player_username=top_user.twitch_username if top_user else None,
                top_player_display_name=top_user.twitch_display_name if top_user else None,
                top_player_avatar_url=top_user.twitch_avatar_url if top_user else None,
            )
        )
    return WeaponStatsResponse(combos=combos_out)
