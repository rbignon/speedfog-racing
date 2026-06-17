"""Daily Seed weekly points scoring.

Single source of truth for:
- The per-daily points formula (compute_daily_points).
- The weekly aggregation (compute_weekly_leaderboard).
- The weekly winners selection (compute_weekly_winners).

The points formula is:

    n = qualified participants (zone_history length >= 2)
    r = participant's rank in the intra-daily ordering
    points(r, n) = round(MAX_DAILY_POINTS * (n - r + 1) / n)

bounded so that only the 1st place ever reaches MAX_DAILY_POINTS (every other
rank is capped at MAX_DAILY_POINTS - 1) and every qualified runner scores at
least 1. The cap and floor only bite on very large fields (n >= ~2*MAX_DAILY_POINTS),
where rounding would otherwise let rank 2 tie the winner or push the tail to 0.

See docs/DAILY_SEED.md (Weekly Points section) for the operational reference.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus, User
from speedfog_racing.services.daily_seed_loop import daily_date_for

# Points awarded to a 1st place, and thus the most a single daily can yield.
# The whole per-rank ladder scales off this; lower ranks earn proportionally less.
# 100 (rather than 50) keeps the cap/floor inactive up to ~199 participants and
# makes a perfect week read as 700; its many divisors also land common field
# sizes on round per-rank values.
MAX_DAILY_POINTS = 100


@dataclass(frozen=True)
class QualifiedParticipant:
    """Minimal projection of a Participant used by the points formula.

    Only qualified participants (zone_history length >= 2) should be passed in.
    """

    participant_id: UUID
    user_id: UUID
    status: ParticipantStatus
    igt_ms: int
    current_layer: int


def _rank_key(qp: QualifiedParticipant) -> tuple[int, int, int]:
    """Sort key for intra-daily ranking.

    FINISHED first (sorted by igt_ms ascending), then ABANDONED (sorted by
    current_layer descending, igt_ms ascending as tie-break).

    This mirrors `websocket.race.manager.sort_leaderboard`, the ordering shown
    to players in the live and results leaderboard. Scoring must not diverge
    from what the leaderboard displays: ranking abandoned runs by how deep they
    reached (current_layer is the monotone max layer), then by how fast.
    """
    if qp.status == ParticipantStatus.FINISHED:
        return (0, qp.igt_ms, 0)
    # Abandoned: deeper current_layer is better -> negate for ascending sort.
    # Within the same layer, lower igt_ms (reached it faster) ranks higher.
    return (1, -qp.current_layer, qp.igt_ms)


def compute_daily_points(
    participants: list[QualifiedParticipant],
) -> dict[UUID, int]:
    """Return a mapping participant_id -> points for one closed daily.

    Implements sport-standard tie ranking: equal sort keys share a rank, the
    next rank skips by the size of the tied group (e.g. two tied at the top
    both get rank 1, the next participant is rank 3).
    """
    n = len(participants)
    if n == 0:
        return {}
    ordered = sorted(participants, key=_rank_key)
    points: dict[UUID, int] = {}
    i = 0
    while i < n:
        rank = i + 1
        sig = _rank_key(ordered[i])
        value = round(MAX_DAILY_POINTS * (n - rank + 1) / n)
        if rank != 1:
            value = min(value, MAX_DAILY_POINTS - 1)  # only the 1st place reaches MAX
        value = max(1, value)  # every qualified runner scores at least 1
        j = i
        while j < n and _rank_key(ordered[j]) == sig:
            points[ordered[j].participant_id] = value
            j += 1
        i = j
    return points


def daily_points_for_race(race: Race) -> dict[UUID, int]:
    """Map participant_id -> points for a race, empty unless it is a closed daily.

    Single source of the "only FINISHED dailies are scored" gate, shared by the
    REST race-detail builder and the WebSocket race_state broadcast so neither
    has to re-derive the qualified projection.
    """
    if race.daily_date is None or race.status != RaceStatus.FINISHED:
        return {}
    qualified = [
        QualifiedParticipant(
            participant_id=p.id,
            user_id=p.user_id,
            status=p.status,
            igt_ms=p.igt_ms,
            current_layer=p.current_layer,
        )
        for p in race.participants
        if len(p.zone_history or []) >= 2
    ]
    return compute_daily_points(qualified)


# --- weekly aggregation ----------------------------------------------------


def _zone_history_len(participant: Participant) -> int:
    history = participant.zone_history or []
    return len(history)


def _aggregate_weapon_combos(
    zone_histories: list[list[dict]],  # type: ignore[type-arg]
) -> list[dict[str, object]]:
    """Mirror of web/src/lib/weapons.ts:aggregateAllCombos.

    Concatenate all `weapons` arrays across the input histories, normalize each
    id (id - id % 1000), sum ticks per normalized combo, return sorted desc.
    """
    totals: dict[tuple[int, ...], int] = {}
    for history in zone_histories:
        for entry in history:
            for combo in entry.get("weapons", []) or []:
                ids = tuple(int(i) - (int(i) % 1000) for i in combo["ids"])
                totals[ids] = totals.get(ids, 0) + int(combo["ticks"])
    return [
        {"ids": list(ids), "ticks": ticks}
        for ids, ticks in sorted(totals.items(), key=lambda kv: -kv[1])
    ]


@dataclass(frozen=True)
class WeeklyUserSummary:
    """User identity fields needed by the weekly leaderboard response."""

    id: UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    equipped_badge_id: str | None
    equipped_name_template_id: str | None
    equipped_phantom_skin_id: str | None


@dataclass(frozen=True)
class WeeklyLeaderboardEntry:
    rank: int
    user: WeeklyUserSummary
    total_points: int
    dailies_played: int
    total_deaths: int
    weapon_combos: list[dict[str, object]] = field(default_factory=list)


@dataclass(frozen=True)
class WeeklyLeaderboardData:
    week_starting: date
    week_ending: date
    dailies_total: int
    entries: list[WeeklyLeaderboardEntry]


async def compute_weekly_leaderboard(
    session: AsyncSession, week_starting: date
) -> WeeklyLeaderboardData:
    """Aggregate points across the closed dailies of the week containing
    `week_starting`. Only Race rows with status == FINISHED contribute."""
    week_ending = week_starting + timedelta(days=7)

    races_q = (
        select(Race)
        .where(
            Race.daily_date >= week_starting,
            Race.daily_date < week_ending,
            Race.status == RaceStatus.FINISHED,
        )
        .options(selectinload(Race.participants).selectinload(Participant.user))
    )
    races = list((await session.execute(races_q)).scalars())

    per_user_points: dict[UUID, int] = {}
    per_user_played: dict[UUID, int] = {}
    per_user_deaths: dict[UUID, int] = {}
    per_user_histories: dict[UUID, list[list[dict]]] = {}  # type: ignore[type-arg]
    per_user_object: dict[UUID, User] = {}

    for race in races:
        qualified: list[QualifiedParticipant] = []
        for p in race.participants:
            if _zone_history_len(p) < 2:
                continue
            qualified.append(
                QualifiedParticipant(
                    participant_id=p.id,
                    user_id=p.user_id,
                    status=p.status,
                    igt_ms=p.igt_ms,
                    current_layer=p.current_layer,
                )
            )
        points = compute_daily_points(qualified)
        for p in race.participants:
            pts = points.get(p.id)
            if pts is None:
                continue
            per_user_points[p.user_id] = per_user_points.get(p.user_id, 0) + pts
            per_user_played[p.user_id] = per_user_played.get(p.user_id, 0) + 1
            per_user_deaths[p.user_id] = per_user_deaths.get(p.user_id, 0) + (p.death_count or 0)
            per_user_histories.setdefault(p.user_id, []).append(p.zone_history or [])
            per_user_object[p.user_id] = p.user

    ranked = sorted(per_user_points.items(), key=lambda kv: -kv[1])
    entries: list[WeeklyLeaderboardEntry] = []
    last_points: int | None = None
    last_rank = 0
    for i, (user_id, pts) in enumerate(ranked):
        if pts != last_points:
            last_rank = i + 1
            last_points = pts
        u = per_user_object[user_id]
        entries.append(
            WeeklyLeaderboardEntry(
                rank=last_rank,
                user=WeeklyUserSummary(
                    id=u.id,
                    twitch_username=u.twitch_username,
                    twitch_display_name=u.twitch_display_name,
                    twitch_avatar_url=u.twitch_avatar_url,
                    equipped_badge_id=u.equipped_badge_id,
                    equipped_name_template_id=u.equipped_name_template_id,
                    equipped_phantom_skin_id=u.equipped_phantom_skin_id,
                ),
                total_points=pts,
                dailies_played=per_user_played[user_id],
                total_deaths=per_user_deaths[user_id],
                weapon_combos=_aggregate_weapon_combos(per_user_histories[user_id]),
            )
        )

    return WeeklyLeaderboardData(
        week_starting=week_starting,
        week_ending=week_ending - timedelta(days=1),
        dailies_total=len(races),
        entries=entries,
    )


# --- winners selection -----------------------------------------------------


def _today() -> date:
    """UTC rotation date. Indirection lets tests freeze the clock via
    monkeypatch. Mirrors `services.daily_seed_loop.daily_date_for` so the
    "past week" boundary aligns with the daily rotation."""
    return daily_date_for(datetime.now(UTC))


async def compute_weekly_winners(
    session: AsyncSession, week_starting: date
) -> list[WeeklyLeaderboardEntry] | None:
    """Return the users tied at max(total_points) for the given week, or None
    if the week is current or future (not yet decided).

    A week is past iff today is on or after the next week's Monday
    (week_starting + 7 days).
    """
    if _today() < week_starting + timedelta(days=7):
        return None
    data = await compute_weekly_leaderboard(session, week_starting)
    if not data.entries:
        return []
    top = data.entries[0].total_points
    return [e for e in data.entries if e.total_points == top]


async def compute_weekly_daily_winners(
    session: AsyncSession, week_starting: date
) -> set[UUID] | None:
    """Return the user ids who ranked 1st on at least one closed daily of the
    given week, or None if the week is current or future (not yet decided).

    A daily win is the top `compute_daily_points` score for that day (ties
    included). Past-week gating mirrors `compute_weekly_winners`.
    """
    if _today() < week_starting + timedelta(days=7):
        return None
    week_ending = week_starting + timedelta(days=7)

    races_q = (
        select(Race)
        .where(
            Race.daily_date >= week_starting,
            Race.daily_date < week_ending,
            Race.status == RaceStatus.FINISHED,
        )
        .options(selectinload(Race.participants))
    )
    races = list((await session.execute(races_q)).scalars())

    winners: set[UUID] = set()
    for race in races:
        points = daily_points_for_race(race)
        if not points:
            continue
        top = max(points.values())
        for p in race.participants:
            if points.get(p.id) == top:
                winners.add(p.user_id)
    return winners
