"""Pydantic schemas for API requests and responses."""

from datetime import UTC, date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from speedfog_racing.models import (
    FeedbackSource,
    ParticipantStatus,
    RaceStatus,
    TrainingSessionStatus,
)


def as_aware_utc(dt: datetime | None) -> datetime | None:
    """Normalize naive datetimes to UTC.

    Public helper so API handlers can apply the same conversion before
    persisting client-supplied datetimes (otherwise a naive value lands on
    a TIMESTAMPTZ column and Postgres re-interprets it through the session
    timezone, which silently shifts the stored instant).
    """
    if dt is None or dt.tzinfo is not None:
        return dt
    return dt.replace(tzinfo=UTC)


# Internal alias kept for backward-compat with the validator below.
_as_aware = as_aware_utc


def validate_late_join_durations(
    *,
    late_join_window_minutes: int | None,
    race_duration_minutes: int | None,
) -> None:
    """Enforce the late-join / race-duration invariants. Raises ValueError on violation.

    Shared between CreateRaceRequest's validator and PATCH /races so a partial
    update cannot leave the race in a state that the create endpoint would
    have rejected.

    Both durations are counted in minutes from ``started_at``; the absolute
    deadlines are computed on read by :func:`compute_late_join_deadlines`.
    """
    if late_join_window_minutes is not None and late_join_window_minutes <= 0:
        raise ValueError("late_join_window_minutes must be > 0")
    if race_duration_minutes is not None and race_duration_minutes <= 0:
        raise ValueError("race_duration_minutes must be > 0")
    if (
        late_join_window_minutes is not None
        and race_duration_minutes is not None
        and late_join_window_minutes > race_duration_minutes
    ):
        raise ValueError("late_join_window_minutes must be <= race_duration_minutes")


# =============================================================================
# Request Schemas
# =============================================================================


class CreateRaceRequest(BaseModel):
    """Request to create a new race."""

    name: str = Field(min_length=1, max_length=200)
    pool_name: str = "standard"
    config: dict[str, Any] = {}
    organizer_participates: bool = False
    scheduled_at: datetime | None = None
    is_public: bool = True
    open_registration: bool = False
    max_participants: int | None = None
    late_join_window_minutes: int | None = None
    race_duration_minutes: int | None = None
    private_dag: bool = False

    @model_validator(mode="after")
    def validate_open_registration(self) -> "CreateRaceRequest":
        if self.open_registration:
            if self.max_participants is None or self.max_participants < 2:
                raise ValueError("max_participants must be >= 2 when open_registration is enabled")
        if self.max_participants is not None and self.max_participants > 100:
            raise ValueError("max_participants cannot exceed 100")
        return self

    @model_validator(mode="after")
    def validate_late_join(self) -> "CreateRaceRequest":
        validate_late_join_durations(
            late_join_window_minutes=self.late_join_window_minutes,
            race_duration_minutes=self.race_duration_minutes,
        )
        return self


class UpdateRaceRequest(BaseModel):
    """Request to update race properties. Organizer only.

    scheduled_at / open_registration / max_participants / private_dag: SETUP only.
    is_public: editable at any status.
    late_join_window_minutes: SETUP only.
    race_duration_minutes: SETUP, or RUNNING to extend (never shorten).
    """

    scheduled_at: datetime | None = None
    is_public: bool | None = None
    open_registration: bool | None = None
    max_participants: int | None = None
    late_join_window_minutes: int | None = None
    race_duration_minutes: int | None = None
    private_dag: bool | None = None


class AddParticipantRequest(BaseModel):
    """Request to add a participant to a race."""

    twitch_username: str


class AddCasterRequest(BaseModel):
    """Request to add a caster to a race."""

    twitch_username: str


class RerollSeedRequest(BaseModel):
    """Optional request body for re-rolling a seed with bug report."""

    report_buggy: bool = False
    report_reason: str | None = Field(None, max_length=500)


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
    equipped_badge_id: str | None = None
    equipped_name_template_id: str | None = None


class ParticipantPreview(UserResponse):
    """User with optional placement for race previews.

    ``status`` and ``igt_ms`` let the daily-page leaderboard render finished
    runs without paying for the full ``ParticipantResponse`` payload.
    """

    placement: int | None = None
    status: ParticipantStatus
    igt_ms: int | None = None


class UserStatsWeekly(BaseModel):
    """Per-category weekly counts since the user joined (capped at 52w)."""

    races: list[int]
    daily: list[int]
    solo: list[int]
    organized: list[int]
    weeks_count: int
    capped: bool


class UserStatsResponse(BaseModel):
    """Aggregated user statistics."""

    race_count: int
    daily_count: int
    training_count: int
    organized_count: int
    casted_count: int
    weekly: UserStatsWeekly


class PoolTypeStatsResponse(BaseModel):
    """Stats for one type (race or training) in a pool."""

    runs: int
    best_time_ms: int | None = None


class UserPoolStatsEntry(BaseModel):
    """Per-pool stats for a user."""

    pool_name: str
    race: PoolTypeStatsResponse | None = None
    training: PoolTypeStatsResponse | None = None
    total_runs: int


class UserPoolStatsResponse(BaseModel):
    """Aggregated pool stats for a user."""

    pools: list[UserPoolStatsEntry]


class ProfileBadge(BaseModel):
    """A badge displayed on a user's profile page."""

    id: str
    name: str
    icon_filename: str
    description: str | None = None


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
    held_badges: list[ProfileBadge] = []
    equipped_name_template_id: str | None = None
    equipped_phantom_skin_id: str | None = None


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
    total_starters: int
    igt_ms: int
    death_count: int
    is_mod_connected: bool = False
    is_organizer: bool = False


class DailyParticipantActivity(ActivityItemBase):
    type: str = "daily_participant"
    race_id: UUID
    daily_date: date
    pool_name: str
    pool_display_name: str | None = None
    status: str
    placement: int | None = None
    total_starters: int
    igt_ms: int
    death_count: int
    is_mod_connected: bool = False


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
    pool_display_name: str | None = None
    status: str
    igt_ms: int
    death_count: int
    exclude_from_stats: bool = False
    is_mod_connected: bool = False


ActivityItem = (
    RaceParticipantActivity
    | RaceOrganizerActivity
    | RaceCasterActivity
    | TrainingActivity
    | DailyParticipantActivity
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
    is_live: bool = False
    stream_url: str | None = None


class RaceResponse(BaseModel):
    """Race information in responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    name: str
    organizer: UserResponse
    status: RaceStatus
    pool_name: str | None
    is_public: bool
    open_registration: bool = False
    max_participants: int | None = None
    created_at: datetime
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    seeds_released_at: datetime | None = None
    late_join_window_minutes: int | None = None
    race_duration_minutes: int | None = None
    registration_closes_at: datetime | None = None
    race_ends_at: datetime | None = None
    private_dag: bool = False
    daily_date: date | None = None
    exclude_from_elo: bool = False
    participant_count: int
    participant_previews: list[ParticipantPreview] = []
    seed_total_layers: int | None = None
    casters: list[CasterResponse] = []
    can_join: bool = False
    my_role: str | None = None
    my_participant_status: ParticipantStatus | None = None
    my_current_layer: int | None = None
    my_igt_ms: int | None = None
    my_death_count: int | None = None


class PoolConfig(BaseModel):
    name: str | None = None
    type: str = "race"
    sort_order: int = 99
    estimated_duration: str | None = None
    description: str | None = None
    min_layers: int | None = None
    max_layers: int | None = None
    final_tier: int | None = None
    starting_runes: int | None = None
    starting_upgrades: list[str] | None = None
    starting_items: list[str] | None = None
    care_package: bool | None = None
    weapon_upgrade: int | None = None
    care_package_items: list[str] | None = None
    items_randomized: bool | None = None
    auto_upgrade_weapons: bool | None = None
    remove_requirements: bool | None = None
    major_boss_ratio: str | None = None
    randomize_bosses: str | None = None
    difficulty_curve: str | None = None
    nerf_gargoyles: bool | None = None
    nerf_malenia: bool | None = None
    allcraft: bool | None = None
    sentry_torch_shop: bool | None = None


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
    open_registration: bool = False
    max_participants: int | None = None
    created_at: datetime
    scheduled_at: datetime | None = None
    started_at: datetime | None = None
    seeds_released_at: datetime | None = None
    late_join_window_minutes: int | None = None
    race_duration_minutes: int | None = None
    registration_closes_at: datetime | None = None
    race_ends_at: datetime | None = None
    private_dag: bool = False
    daily_date: date | None = None
    exclude_from_elo: bool = False
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


# =============================================================================
# Daily Week Grid Schemas
# =============================================================================


class DailyPodiumEntry(BaseModel):
    """Podium entry for a daily race."""

    placement: int
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    igt_ms: int


class DailyMyResult(BaseModel):
    """Current user's result in a daily race."""

    status: ParticipantStatus
    placement: int | None  # only when status == FINISHED
    total_starters: int
    igt_ms: int | None  # only when status == FINISHED
    death_count: int


class DailyWeekDay(BaseModel):
    """Information about a single day in the daily week grid."""

    weekday: int  # 0=Mon .. 6=Sun
    date: date
    state: Literal["missing_past", "past", "today", "future"]
    pool_name: str | None
    pool_display_name: str | None
    race_id: str | None  # uuid; None for missing_past, future, today-pending
    started_at: datetime | None
    ends_at: datetime | None
    starters_count: int  # participants who launched their run (igt_ms > 0)
    participants_count: int  # all sign-ups including no-shows; for "today" social proof
    podium: list[DailyPodiumEntry]
    my_result: DailyMyResult | None


class DailyWeekResponse(BaseModel):
    """Response for the daily week grid endpoint."""

    week_start: date
    today: date
    days: list[DailyWeekDay]
    has_earlier: bool


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
    exclude_from_stats: bool = False


class TrainingSessionResponse(BaseModel):
    """Training session in list responses."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user: UserResponse
    status: TrainingSessionStatus
    pool_name: str
    pool_display_name: str | None = None
    igt_ms: int
    death_count: int
    exclude_from_stats: bool
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
    exclude_from_stats: bool
    zone_history: list[dict[str, Any]] | None = None
    created_at: datetime
    finished_at: datetime | None = None
    seed_number: str | None = None
    seed_total_layers: int | None = None
    seed_total_nodes: int | None = None
    seed_total_paths: int | None = None
    graph_json: dict[str, Any] | None = None
    pool_config: PoolConfig | None = None


class GhostResponse(BaseModel):
    """Anonymous ghost data for replay."""

    zone_history: list[dict[str, Any]]
    igt_ms: int
    death_count: int


# --- Stats ---


class LeaderboardPlayer(BaseModel):
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    elo_rating: int
    elo_races: int
    trend_delta: int
    avg_opponent_elo: int | None = None
    equipped_badge_id: str | None = None
    equipped_name_template_id: str | None = None


class CommunityStats(BaseModel):
    total_races: int
    active_players: int
    ranked_players: int
    total_deaths: int
    hours_raced: float


class LeaderboardResponse(BaseModel):
    players: list[LeaderboardPlayer]
    community: CommunityStats


class ZoneStatEntry(BaseModel):
    display_name: str
    type: str
    total_deaths: int
    avg_deaths_per_visit: float


class ZoneBacktrackEntry(BaseModel):
    display_name: str
    type: str
    backtrack_count: int
    avg_backtracks_per_race: float


class ZoneTimeEntry(BaseModel):
    display_name: str
    type: str
    avg_time_ms: int
    visits: int


class ZoneStatsResponse(BaseModel):
    deadliest: list[ZoneStatEntry]
    most_backtracked: list[ZoneBacktrackEntry]
    slowest: list[ZoneTimeEntry]
    fastest: list[ZoneTimeEntry]


class BossStatEntry(BaseModel):
    display_name: str
    type: str
    encounters: int
    avg_deaths: float
    max_deaths: int
    avg_time_ms: int
    back_ratio: float


class BossStatsResponse(BaseModel):
    bosses: list[BossStatEntry]


class TraitPlayerEntry(BaseModel):
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None
    score: int
    elo_rating: int


class PlayerProfilesResponse(BaseModel):
    profiles: dict[str, list[TraitPlayerEntry]]


class TraitScoresDetail(BaseModel):
    rusher: int
    cautious: int
    resilient: int
    rage_quitter: int
    explorer: int
    pathfinder: int
    boss_slayer: int


class UserTraitsResponse(BaseModel):
    dominant_trait: str | None
    dominant_description: str | None
    scores: TraitScoresDetail | None
    finished_races: int
    races_required: int
    elo_rating: int
    elo_rank: int | None
    elo_trend_delta: int


# =============================================================================
# Feedback Schemas
# =============================================================================


class FeedbackCreate(BaseModel):
    """Payload for submitting user feedback."""

    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=1000)
    source: FeedbackSource
    race_id: UUID | None = None


class FeedbackResponse(BaseModel):
    """Feedback row returned to the submitter."""

    id: UUID
    rating: int
    comment: str | None
    source: FeedbackSource
    race_id: UUID | None
    races_played_at_feedback: int
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class AdminFeedbackUser(BaseModel):
    """User info joined into admin feedback listings."""

    id: UUID
    twitch_username: str
    twitch_display_name: str | None

    model_config = ConfigDict(from_attributes=True)


class AdminFeedbackRace(BaseModel):
    """Race info joined into admin feedback listings (extensible with more fields later)."""

    id: UUID

    model_config = ConfigDict(from_attributes=True)


class AdminFeedbackItem(BaseModel):
    """Feedback row with joined user and race info (admin view)."""

    id: UUID
    rating: int
    comment: str | None
    source: FeedbackSource
    race_id: UUID | None
    races_played_at_feedback: int
    created_at: datetime
    user: AdminFeedbackUser
    race: AdminFeedbackRace | None

    model_config = ConfigDict(from_attributes=True)


class AdminFeedbackListResponse(BaseModel):
    """Paginated admin feedback list with aggregate stats."""

    items: list[AdminFeedbackItem]
    total: int
    average_rating: float | None
    distribution: dict[int, int]
