"""Daily Seed weekly points scoring.

Single source of truth for:
- The per-daily points formula (compute_daily_points).
- The weekly aggregation (compute_weekly_leaderboard).
- The weekly winners selection (compute_weekly_winners).

The points formula is:

    n = qualified participants (zone_history length >= 2)
    r = participant's rank in the intra-daily ordering
    points(r, n) = round(50 * (n - r + 1) / n)

See docs/specs/2026-05-30-daily-weekly-points-design.md for the full rationale.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceStatus, User


@dataclass(frozen=True)
class QualifiedParticipant:
    """Minimal projection of a Participant used by the points formula.

    Only qualified participants (zone_history length >= 2) should be passed in.
    """

    participant_id: UUID
    user_id: UUID
    status: ParticipantStatus
    igt_ms: int
    zone_history_len: int


def _rank_key(qp: QualifiedParticipant) -> tuple[int, int, int]:
    """Sort key for intra-daily ranking.

    FINISHED first (sorted by igt_ms ascending), then ABANDONED (sorted by
    zone_history_len descending, igt_ms descending as tie-break).
    """
    if qp.status == ParticipantStatus.FINISHED:
        return (0, qp.igt_ms, 0)
    # Abandoned: higher zone_history_len is better -> negate for ascending sort.
    # Within same zone_history_len, higher igt_ms is better -> negate as well.
    return (1, -qp.zone_history_len, -qp.igt_ms)


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
        j = i
        while j < n and _rank_key(ordered[j]) == sig:
            points[ordered[j].participant_id] = round(50 * (n - rank + 1) / n)
            j += 1
        i = j
    return points


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
                    zone_history_len=_zone_history_len(p),
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
    """UTC today. Indirection lets tests freeze the clock via monkeypatch."""
    return datetime.now(UTC).date()


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
