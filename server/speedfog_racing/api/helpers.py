"""Shared API response helpers."""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import (
    Caster,
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    User,
    compute_late_join_deadlines,
)
from speedfog_racing.schemas import (
    CasterResponse,
    ParticipantPreview,
    ParticipantResponse,
    RaceResponse,
    UserResponse,
)
from speedfog_racing.services.twitch_live import twitch_live_service


def late_join_window_open(race: Race, now: datetime) -> bool:
    """True iff the race is RUNNING with an open late-join registration window.

    Does NOT consult open_registration; the caller composes that where relevant.
    """
    if race.status != RaceStatus.RUNNING:
        return False
    closes, _ = compute_late_join_deadlines(race)
    if closes is None:
        return False
    return closes > now


def race_date(race: Race) -> datetime:
    """Best date for a race: started_at > scheduled_at > created_at."""
    return race.started_at or race.scheduled_at or race.created_at


def format_pool_display_name(pool: Pool | None) -> str:
    """Format a pool for display using the config's display name.

    Uses the pool's cached config name if present; falls back to title-casing
    the raw pool name (e.g. ``training_standard`` → ``Training Standard``).
    """
    if pool is None:
        return "Unknown"
    name = pool.config.get("name") if pool.config else None
    if name:
        return str(name)
    return pool.name.replace("_", " ").title()


def user_response(user: User) -> UserResponse:
    """Convert User model to UserResponse."""
    return UserResponse(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
    )


def participant_preview(
    participant: Participant, placement: int | None = None
) -> ParticipantPreview:
    """Convert Participant model to ParticipantPreview.

    ``igt_ms`` is only meaningful for finished runs; for any other status
    the participant has not produced a final time yet, so we surface
    ``None`` to keep the daily-page leaderboard honest.
    """
    user = participant.user
    return ParticipantPreview(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
        placement=placement,
        status=participant.status,
        igt_ms=(
            participant.igt_ms
            if participant.status == ParticipantStatus.FINISHED and participant.igt_ms
            else None
        ),
    )


def participant_response(participant: Participant) -> ParticipantResponse:
    """Convert Participant model to ParticipantResponse."""
    return ParticipantResponse(
        id=participant.id,
        user=user_response(participant.user),
        status=participant.status,
        current_layer=participant.current_layer,
        igt_ms=participant.igt_ms,
        death_count=participant.death_count,
        color_index=participant.color_index,
    )


def caster_response(caster: Caster) -> CasterResponse:
    """Convert Caster model to CasterResponse."""
    username = caster.user.twitch_username
    return CasterResponse(
        id=caster.id,
        user=user_response(caster.user),
        is_live=twitch_live_service.is_live(username),
        stream_url=twitch_live_service.stream_url(username),
    )


def race_response(race: Race, user: User | None = None) -> RaceResponse:
    """Convert Race model to RaceResponse."""
    if race.status == RaceStatus.FINISHED:
        finished = sorted(
            [p for p in race.participants if p.status == ParticipantStatus.FINISHED],
            key=lambda p: p.igt_ms,
        )
        non_finished = [p for p in race.participants if p.status != ParticipantStatus.FINISHED]
        all_previews = [participant_preview(p, placement=i + 1) for i, p in enumerate(finished)] + [
            participant_preview(p) for p in non_finished
        ]
        previews = all_previews[:5]
    else:
        previews = [participant_preview(p) for p in race.participants[:5]]

    # Compute can_join and my_role
    now = datetime.now(UTC)
    participant_count = len(race.participants)
    is_full = race.max_participants is not None and participant_count >= race.max_participants
    is_open_setup = race.open_registration and race.status == RaceStatus.SETUP
    is_open_late_join = race.open_registration and late_join_window_open(race, now)
    casters = race.casters if "casters" in race.__dict__ else []

    my_role: str | None = None
    my_participant: Participant | None = None
    if user is not None:
        my_participant = next((p for p in race.participants if p.user_id == user.id), None)
        if race.organizer_id == user.id:
            my_role = "organizing"
        elif my_participant is not None:
            my_role = "participating"
        elif any(c.user_id == user.id for c in casters):
            my_role = "casting"

    if not (is_open_setup or is_open_late_join) or is_full:
        can_join = False
    elif user is None:
        can_join = True
    else:
        can_join = my_role is None

    registration_closes_at, race_ends_at = compute_late_join_deadlines(race)
    return RaceResponse(
        id=race.id,
        name=race.name,
        organizer=user_response(race.organizer),
        status=race.status,
        pool_name=race.seed.pool_name if race.seed else None,
        is_public=race.is_public,
        open_registration=race.open_registration,
        max_participants=race.max_participants,
        created_at=race.created_at,
        scheduled_at=race.scheduled_at,
        started_at=race.started_at,
        seeds_released_at=race.seeds_released_at,
        late_join_window_minutes=race.late_join_window_minutes,
        race_duration_minutes=race.race_duration_minutes,
        registration_closes_at=registration_closes_at,
        race_ends_at=race_ends_at,
        private_dag=race.private_dag,
        daily_date=race.daily_date,
        exclude_from_elo=race.exclude_from_elo,
        participant_count=participant_count,
        participant_previews=previews,
        casters=[caster_response(c) for c in race.casters] if "casters" in race.__dict__ else [],
        can_join=can_join,
        my_role=my_role,
        my_participant_status=my_participant.status if my_participant else None,
        my_current_layer=my_participant.current_layer if my_participant else None,
        my_igt_ms=my_participant.igt_ms if my_participant else None,
        my_death_count=my_participant.death_count if my_participant else None,
    )


async def compute_race_stats(
    db: AsyncSession, race_ids: Sequence[uuid.UUID]
) -> tuple[dict[uuid.UUID, int], dict[tuple[uuid.UUID, uuid.UUID], int]]:
    """Compute participant counts and placements for a batch of races.

    Returns:
        total_by_race: {race_id: total_participant_count}
        placements: {(race_id, participant_id): 1-based placement}
                    Only includes finished participants.
    """
    if not race_ids:
        return {}, {}

    count_q = await db.execute(
        select(Participant.race_id, func.count().label("total"))
        .where(Participant.race_id.in_(race_ids))
        .group_by(Participant.race_id)
    )
    total_by_race = {row.race_id: row.total for row in count_q}

    finished_q = await db.execute(
        select(Participant.race_id, Participant.id)
        .where(
            Participant.race_id.in_(race_ids),
            Participant.status == ParticipantStatus.FINISHED,
        )
        .order_by(Participant.race_id, Participant.igt_ms, Participant.finished_at)
    )
    placements: dict[tuple[uuid.UUID, uuid.UUID], int] = {}
    current_race_id: uuid.UUID | None = None
    rank = 0
    for row in finished_q:
        if row.race_id != current_race_id:
            current_race_id = row.race_id
            rank = 0
        rank += 1
        placements[(row.race_id, row.id)] = rank

    return total_by_race, placements
