"""Stats API routes: overview, zones, bosses, player profiles."""

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median
from time import monotonic
from typing import Any, TypeVar, cast
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.database import get_db
from speedfog_racing.models import (
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
    HeatmapResponse,
    PlayerProfilesResponse,
    StatsOverviewResponse,
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


@router.get("/overview", response_model=StatsOverviewResponse)
async def get_stats_overview(db: AsyncSession = Depends(get_db)) -> StatsOverviewResponse:
    """Community-wide activity KPIs with 20-week trends."""
    from speedfog_racing.services.analytics_service import compute_public_overview

    async def _compute() -> StatsOverviewResponse:
        data = await compute_public_overview(db)
        return StatsOverviewResponse(**data)

    return await _cached("overview", _compute)


@router.get("/heatmap", response_model=HeatmapResponse)
async def get_stats_heatmap(
    tz: str | None = Query(default=None, max_length=50),
    db: AsyncSession = Depends(get_db),
) -> HeatmapResponse:
    """Community activity heatmap, bucketed in the requested timezone."""
    from speedfog_racing.services.analytics_service import compute_public_heatmap

    try:
        resolved = tz if tz and ZoneInfo(tz) else "UTC"
    except Exception:
        resolved = "UTC"

    async def _compute() -> HeatmapResponse:
        data = await compute_public_heatmap(db, tz)
        return HeatmapResponse(**data)

    return await _cached(f"heatmap:{resolved}", _compute)


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
    # 0-indexed layer in the owning seed's graph. Meaningful per seed (the
    # same cluster can sit at different layers across seeds), so read it from
    # the participant's own SeedNodes, never from the merged node_display.
    layer: int


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

T = TypeVar("T")

# In-process TTL cache for the public aggregation endpoints. Values are the
# response models themselves (a few KB each); single-flight per key so
# concurrent cold hits compute once instead of stampeding a 4s aggregation.
# Entries are never evicted early (only overwritten on next access past their
# TTL), so the dict's size is bounded by the number of distinct keys ever
# requested, not by time. Like ``_seed_nodes_cache`` above, this is fine
# because the key space is small in practice (a handful of pool names, a
# capped ``days`` range on real UI calls, a finite zone-codex ``node_id``
# set); it is not a hard cap against an adversarial client varying ``days``.
STATS_CACHE_TTL = 60.0

_stats_cache: dict[str, tuple[float, Any]] = {}
_stats_cache_locks: dict[str, asyncio.Lock] = {}


async def _cached(key: str, compute: Callable[[], Awaitable[T]]) -> T:
    hit = _stats_cache.get(key)
    if hit is not None and hit[0] > monotonic():
        return cast(T, hit[1])
    lock = _stats_cache_locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _stats_cache.get(key)
        if hit is not None and hit[0] > monotonic():
            return cast(T, hit[1])
        value = await compute()
        _stats_cache[key] = (monotonic() + STATS_CACHE_TTL, value)
        return value


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
            layer=meta.get("layer") or 0,
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

        # Per-participant time accumulation (mirrors tools/extract_zone_times.py):
        # every visit's duration sums into the zone's total, and whether the
        # total counts is decided by the outcome of the LAST visit only.
        node_total_ms: dict[str, int] = {}
        node_last_idx: dict[str, int] = {}

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
            # A visit is an entry the player chose to make (fog gate traversal,
            # or legacy untyped entries treated as fog). Warp landings (type
            # "backtrack") put the player there without a decision, and can
            # never be turn-aways, so counting them would dilute backtrack_rate
            # on hub zones whose grace serves as a respawn anchor.
            if entry.get("type", "fog") != "backtrack":
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

            # Time: this visit lasts until the next entry (or the participant's
            # final IGT for the last one) and accumulates into the zone total.
            current_igt = entry.get("igt_ms", 0)
            if idx + 1 < len(history):
                end_igt = history[idx + 1].get("igt_ms", 0)
            else:
                end_igt = participant.igt_ms or 0
            if end_igt > current_igt:
                node_total_ms[nid] = node_total_ms.get(nid, 0) + (end_igt - current_igt)
            node_last_idx[nid] = idx

        # A zone's total only counts if the participant CLEARED it: their last
        # visit left toward a higher layer, or ended a FINISHED run. Without
        # this filter, peeks, abandons and warp exits would deflate the time
        # stats with truncated durations, and precisely on the most
        # backtracked zones.
        for nid, total_ms in node_total_ms.items():
            last_idx = node_last_idx[nid]
            if last_idx + 1 < len(history):
                next_info = nodes.get(history[last_idx + 1].get("node_id", ""))
                cleared = next_info is not None and next_info.layer > nodes[nid].layer
            else:
                cleared = participant.status == ParticipantStatus.FINISHED
            if cleared:
                zone_times.setdefault(nid, []).append(total_ms)

        # Count abandon as backtrack for the participant's last zone (they
        # renounced there), but only on a first visit, and never on a warp
        # landing: a landing is not a place the player chose to be (the zone
        # they turned away from already got its credit above), and crediting
        # it would break the backtrack_count <= visits invariant that lets
        # backtrack_rate be a percentage.
        if (
            participant.status == ParticipantStatus.ABANDONED
            and history
            and history[-1].get("type", "fog") != "backtrack"
        ):
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
            # .get: a zone seen only through warp landings has deaths/races
            # but no chosen visits
            m["visits"] += zone_visits.get(nid, 0)
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
                "visits": zone_visits.get(nid, 0),
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

    async def _compute() -> ZoneStatsResponse:
        participants, seeds_by_id = await _load_zone_stats_inputs(pool, days, db)

        node_display = _resolve_node_display(seeds_by_id)
        node_data = _aggregate_zone_stats(
            participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
        )

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

        # Most backtracked: by share of visits ending in a turn-away. Every
        # counted backtrack is a distinct non-landing entry of the zone, so the
        # rate is bounded to [0, 1] and visits > 0 whenever backtrack_count > 0.
        backtracked_nodes = sorted(
            [n for n in node_data.values() if n["backtrack_count"] > 0],
            key=lambda n: n["backtrack_count"] / n["visits"],
            reverse=True,
        )[:5]
        most_backtracked = [
            ZoneBacktrackEntry(
                node_id=n["node_id"],
                display_name=n["short_name"],
                type=n["type"],
                backtrack_count=n["backtrack_count"],
                backtrack_rate=round(n["backtrack_count"] / n["visits"], 2),
            )
            for n in backtracked_nodes
        ]

        # Slowest: zones with highest median clear time
        slowest_nodes = sorted(
            [n for n in node_data.values() if n["times"]],
            key=lambda n: median(n["times"]),
            reverse=True,
        )[:5]
        slowest = [
            ZoneTimeEntry(
                node_id=n["node_id"],
                display_name=n["short_name"],
                type=n["type"],
                median_time_ms=round(median(n["times"])),
                players=len(n["times"]),
            )
            for n in slowest_nodes
        ]

        # Fastest: zones with lowest median clear time (min 3 players to avoid outliers)
        fastest_nodes = sorted(
            [n for n in node_data.values() if len(n["times"]) >= 3],
            key=lambda n: median(n["times"]),
        )[:5]
        fastest = [
            ZoneTimeEntry(
                node_id=n["node_id"],
                display_name=n["short_name"],
                type=n["type"],
                median_time_ms=round(median(n["times"])),
                players=len(n["times"]),
            )
            for n in fastest_nodes
        ]

        return ZoneStatsResponse(
            deadliest=deadliest,
            most_backtracked=most_backtracked,
            slowest=slowest,
            fastest=fastest,
        )

    return await _cached(f"zones:{pool}:{days}", _compute)


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

    async def _compute() -> ZoneIndexResponse:
        participants, seeds_by_id = await _load_zone_stats_inputs(pool, days, db)
        node_display = _resolve_node_display(seeds_by_id)
        node_data = _aggregate_zone_stats(
            participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
        )
        zones = [
            ZoneIndexEntry(
                node_id=data["node_id"],
                display_name=data["display_name"],
                type=data["type"],
                visits=data["visits"],
                median_time_ms=round(median(data["times"])) if data["times"] else 0,
                fastest_time_ms=min(data["times"]) if data["times"] else 0,
                avg_deaths_per_visit=(
                    round(data["total_deaths"] / data["visits"], 2) if data["visits"] else 0.0
                ),
                backtrack_rate=(
                    round(data["backtrack_count"] / data["visits"], 2) if data["visits"] else 0.0
                ),
                zones=data["zones"],
            )
            for data in node_data.values()
        ]
        zones.sort(key=lambda z: z.display_name)
        return ZoneIndexResponse(zones=zones)

    return await _cached(f"zones_index:{pool}:{days}", _compute)


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
    (``median_time_ms=None``, ``visits=0``, ...) when the zone is known but has
    no visits within the ``days`` window. ``display_name`` is the FULL name
    (same as the index, unlike the top-5 panels on ``/zones``).
    """

    async def _compute() -> ZoneDetailResponse:
        participants, seeds_by_id = await _load_zone_stats_inputs(pool, days, db)
        node_display = _resolve_node_display(seeds_by_id)
        info = node_display.get(node_id)
        if info is None:
            raise HTTPException(status_code=404, detail="Unknown zone")
        if info.type not in DUNGEON_NODE_TYPES:
            raise HTTPException(status_code=404, detail="Not an explorable zone")
        node_data = _aggregate_zone_stats(
            participants, seeds_by_id, DUNGEON_NODE_TYPES, node_display
        )
        data = node_data.get(info.full_name)
        if data is None:
            return ZoneDetailResponse(
                node_id=node_id,
                display_name=info.full_name,
                type=info.type,
                visits=0,
                race_count=0,
                median_time_ms=None,
                fastest_time_ms=None,
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
            median_time_ms=round(median(data["times"])) if data["times"] else None,
            fastest_time_ms=min(data["times"]) if data["times"] else None,
            avg_deaths_per_visit=(
                round(data["total_deaths"] / data["visits"], 2) if data["visits"] else 0.0
            ),
            zones=list(info.zones),
            backtrack_rate=(
                round(data["backtrack_count"] / data["visits"], 2) if data["visits"] else 0.0
            ),
        )

    return await _cached(f"zone:{node_id}:{pool}:{days}", _compute)


@router.get("/bosses", response_model=BossStatsResponse)
async def get_boss_stats(
    pool: str | None = Query(default=None),
    db: AsyncSession = Depends(get_db),
) -> BossStatsResponse:
    """Boss encounter stats."""

    async def _compute() -> BossStatsResponse:
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
                time_ms = (
                    next_igt - current_igt if current_igt > 0 and next_igt > current_igt else None
                )

                # Resolve boss name from this participant's seed
                node_meta = nodes[nid]
                boss_name = (
                    node_meta.get("boss_name") or node_meta.get("display_name", nid)
                ).rsplit(" - ", 1)[-1]
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
                    back_ratio=round(backed_count / total_encounters, 2)
                    if total_encounters
                    else 0.0,
                )
            )

        boss_entries.sort(key=lambda b: b.avg_deaths, reverse=True)

        return BossStatsResponse(bosses=boss_entries)

    return await _cached(f"bosses:{pool}", _compute)


@router.get("/players", response_model=PlayerProfilesResponse)
async def get_player_profiles(db: AsyncSession = Depends(get_db)) -> PlayerProfilesResponse:
    """Player profiles grouped by dominant trait, top 10 per trait."""

    async def _compute() -> PlayerProfilesResponse:
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
            trait_rows_sorted = sorted(
                trait_rows, key=lambda r: getattr(r[0], trait, 0), reverse=True
            )[:10]
            profiles[trait] = [
                TraitPlayerEntry(
                    twitch_username=user.twitch_username,
                    twitch_display_name=user.twitch_display_name,
                    twitch_avatar_url=user.twitch_avatar_url,
                    score=getattr(scores, trait, 0),
                )
                for scores, user in trait_rows_sorted
            ]

        return PlayerProfilesResponse(profiles=profiles)

    return await _cached("players", _compute)


@router.get("/weapons", response_model=WeaponStatsResponse)
async def get_weapon_stats(
    pool: str | None = Query(default=None),
    days: int = Query(default=30, ge=1, le=3650),
    db: AsyncSession = Depends(get_db),
) -> WeaponStatsResponse:
    """Top weapon combos by total ticks across recent public finished races."""

    async def _compute() -> WeaponStatsResponse:
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

    return await _cached(f"weapons:{pool}:{days}", _compute)
