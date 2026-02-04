"""Pydantic schemas for API requests and responses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from speedfog_racing.models import ParticipantStatus, RaceStatus

# =============================================================================
# Request Schemas
# =============================================================================


class CreateRaceRequest(BaseModel):
    """Request to create a new race."""

    name: str
    pool_name: str = "standard"
    config: dict[str, Any] = {}


class AddParticipantRequest(BaseModel):
    """Request to add a participant to a race."""

    twitch_username: str


class StartRaceRequest(BaseModel):
    """Request to start a race."""

    scheduled_start: datetime


# =============================================================================
# Response Schemas
# =============================================================================


class UserResponse(BaseModel):
    """User information in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None


class ParticipantResponse(BaseModel):
    """Participant information in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user: UserResponse
    status: ParticipantStatus
    current_layer: int
    igt_ms: int
    death_count: int


class RaceResponse(BaseModel):
    """Race information in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organizer: UserResponse
    status: RaceStatus
    pool_name: str | None
    scheduled_start: datetime | None
    created_at: datetime
    participant_count: int


class RaceDetailResponse(BaseModel):
    """Detailed race information with participants."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organizer: UserResponse
    status: RaceStatus
    pool_name: str | None
    scheduled_start: datetime | None
    created_at: datetime
    participant_count: int
    seed_total_layers: int | None
    participants: list[ParticipantResponse]


class RaceListResponse(BaseModel):
    """Response for race listing."""

    races: list[RaceResponse]


class InviteInfoResponse(BaseModel):
    """Public information about an invite."""

    token: str
    race_name: str
    organizer_name: str
    race_status: RaceStatus
    twitch_username: str


class InviteResponse(BaseModel):
    """Response when an invite is created."""

    model_config = ConfigDict(from_attributes=True)

    token: str
    twitch_username: str
    race_id: UUID


class AddParticipantResponse(BaseModel):
    """Response when adding a participant."""

    participant: ParticipantResponse | None = None
    invite: InviteResponse | None = None


class AcceptInviteResponse(BaseModel):
    """Response when accepting an invite."""

    participant: ParticipantResponse
    race_id: UUID
