"""Shared API response helpers."""

from speedfog_racing.models import Participant, Race, User
from speedfog_racing.schemas import ParticipantResponse, RaceResponse, UserResponse


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
    )


def race_response(race: Race) -> RaceResponse:
    """Convert Race model to RaceResponse."""
    return RaceResponse(
        id=race.id,
        name=race.name,
        organizer=user_response(race.organizer),
        status=race.status,
        pool_name=race.seed.pool_name if race.seed else None,
        created_at=race.created_at,
        participant_count=len(race.participants),
    )
