"""Shared API response helpers."""

from speedfog_racing.models import Caster, Participant, Race, User
from speedfog_racing.schemas import (
    CasterResponse,
    ParticipantResponse,
    RaceResponse,
    UserResponse,
)


def format_pool_display_name(pool_name: str | None) -> str:
    """Format a pool name for display: 'training_standard' → 'Standard'."""
    name = pool_name or "unknown"
    if name.startswith("training_"):
        name = name.removeprefix("training_")
    return name.replace("_", " ").title()


def user_response(user: User) -> UserResponse:
    """Convert User model to UserResponse."""
    return UserResponse(
        id=user.id,
        twitch_username=user.twitch_username,
        twitch_display_name=user.twitch_display_name,
        twitch_avatar_url=user.twitch_avatar_url,
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
    return CasterResponse(
        id=caster.id,
        user=user_response(caster.user),
    )


def race_response(race: Race) -> RaceResponse:
    """Convert Race model to RaceResponse."""
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
        participant_count=len(race.participants),
        participant_previews=[user_response(p.user) for p in race.participants[:5]],
        casters=[caster_response(c) for c in race.casters] if "casters" in race.__dict__ else [],
    )
