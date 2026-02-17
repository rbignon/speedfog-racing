"""Pydantic schemas for API requests and responses."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict

from speedfog_racing.models import ParticipantStatus, RaceStatus, TrainingSessionStatus

# =============================================================================
# Request Schemas
# =============================================================================


class CreateRaceRequest(BaseModel):
    """Request to create a new race."""

    name: str
    pool_name: str = "standard"
    config: dict[str, Any] = {}
    organizer_participates: bool = False
    scheduled_at: datetime | None = None
    is_public: bool = True


class UpdateRaceRequest(BaseModel):
    """Request to update race properties (DRAFT/OPEN only).

    All fields use a sentinel pattern: None means "don't change".
    For scheduled_at, use explicit null in JSON to clear the value.
    """

    scheduled_at: datetime | None = None
    is_public: bool | None = None


class AddParticipantRequest(BaseModel):
    """Request to add a participant to a race."""

    twitch_username: str


class AddCasterRequest(BaseModel):
    """Request to add a caster to a race."""

    twitch_username: str


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


class BestRecentPlacement(BaseModel):
    """Best placement among recent finished races."""

    placement: int
    race_name: str
    race_id: UUID
    finished_at: datetime | None


class UserStatsResponse(BaseModel):
    """Aggregated user statistics."""

    race_count: int
    training_count: int
    podium_count: int
    first_place_count: int
    organized_count: int
    casted_count: int
    podium_rate: float | None = None
    best_recent_placement: BestRecentPlacement | None = None


class UserProfileDetailResponse(BaseModel):
    """Public user profile with stats."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    role: str
    created_at: datetime
    stats: UserStatsResponse


class ActivityItemBase(BaseModel):
    """Base for activity timeline items."""

    type: str
    date: datetime
    user: UserResponse | None = None


class RaceParticipantActivity(ActivityItemBase):
    type: str = "race_participant"
    race_id: UUID
    race_name: str
    status: str
    placement: int | None = None
    total_participants: int
    igt_ms: int
    death_count: int


class RaceOrganizerActivity(ActivityItemBase):
    type: str = "race_organizer"
    race_id: UUID
    race_name: str
    status: str
    participant_count: int


class RaceCasterActivity(ActivityItemBase):
    type: str = "race_caster"
    race_id: UUID
    race_name: str
    status: str


class TrainingActivity(ActivityItemBase):
    type: str = "training"
    session_id: UUID
    pool_name: str
    status: str
    igt_ms: int
    death_count: int


ActivityItem = (
    RaceParticipantActivity | RaceOrganizerActivity | RaceCasterActivity | TrainingActivity
)


class ActivityTimelineResponse(BaseModel):
    items: list[ActivityItem]
    total: int
    has_more: bool


class ParticipantResponse(BaseModel):
    """Participant information in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user: UserResponse
    status: ParticipantStatus
    current_layer: int
    igt_ms: int
    death_count: int
    color_index: int = 0


class CasterResponse(BaseModel):
    """Caster information in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user: UserResponse


class RaceResponse(BaseModel):
    """Race information in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organizer: UserResponse
    status: RaceStatus
    pool_name: str | None
    is_public: bool
    created_at: datetime
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    participant_count: int
    participant_previews: list[UserResponse] = []
    seed_total_layers: int | None = None
    my_current_layer: int | None = None
    my_igt_ms: int | None = None
    my_death_count: int | None = None


class PoolConfig(BaseModel):
    type: str = "race"
    estimated_duration: str | None = None
    description: str | None = None
    legacy_dungeons: int | None = None
    min_layers: int | None = None
    max_layers: int | None = None
    final_tier: int | None = None
    starting_items: list[str] | None = None
    care_package: bool | None = None
    weapon_upgrade: int | None = None
    care_package_items: list[str] | None = None
    items_randomized: bool | None = None
    auto_upgrade_weapons: bool | None = None
    remove_requirements: bool | None = None


class PendingInviteResponse(BaseModel):
    """Pending invite information. Token only included for the organizer."""

    id: UUID
    twitch_username: str
    created_at: datetime
    token: str | None = None


class RaceDetailResponse(BaseModel):
    """Detailed race information with participants."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organizer: UserResponse
    status: RaceStatus
    pool_name: str | None
    is_public: bool
    created_at: datetime
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    participant_count: int
    seed_number: str | None = None
    seed_total_layers: int | None
    seed_total_nodes: int | None = None
    seed_total_paths: int | None = None
    participants: list[ParticipantResponse]
    casters: list[CasterResponse] = []
    pending_invites: list[PendingInviteResponse] = []
    pool_config: PoolConfig | None = None


class RaceListResponse(BaseModel):
    """Response for race listing."""

    races: list[RaceResponse]
    total: int | None = None
    has_more: bool | None = None


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


# =============================================================================
# Training Schemas
# =============================================================================


class CreateTrainingRequest(BaseModel):
    """Request to create a training session."""

    pool_name: str = "training_standard"


class TrainingSessionResponse(BaseModel):
    """Training session in list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user: UserResponse
    status: TrainingSessionStatus
    pool_name: str
    igt_ms: int
    death_count: int
    created_at: datetime
    finished_at: datetime | None = None
    seed_total_layers: int | None = None
    seed_total_nodes: int | None = None
    current_layer: int = 0


class TrainingSessionDetailResponse(BaseModel):
    """Detailed training session with graph data."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user: UserResponse
    status: TrainingSessionStatus
    pool_name: str
    igt_ms: int
    death_count: int
    progress_nodes: list[dict[str, Any]] | None = None
    created_at: datetime
    finished_at: datetime | None = None
    seed_number: str | None = None
    seed_total_layers: int | None = None
    seed_total_nodes: int | None = None
    seed_total_paths: int | None = None
    graph_json: dict[str, Any] | None = None
    pool_config: PoolConfig | None = None
