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
    is_public: bool = False
    open_registration: bool = False
    max_participants: int | None = None
    late_join_window_minutes: int | None = None
    race_duration_minutes: int | None = None
    private_dag: bool = False
    deathless: bool = False
    custom_rules: str | None = Field(default=None, max_length=1000)

    @model_validator(mode="after")
    def validate_open_registration(self) -> "CreateRaceRequest":
        if self.open_registration:
            if self.max_participants is None or self.max_participants < 2:
                raise ValueError("max_participants must be >= 2 when open_registration is enabled")
        if self.max_participants is not None and self.max_participants > 100:
            raise ValueError("max_participants cannot exceed 100")
        return self

    @model_validator(mode="after")
    def validate_public_requires_schedule(self) -> "CreateRaceRequest":
        # Public races are announced on Discord and listed on the homepage,
        # so an announcement without a scheduled time gives no useful info.
        if self.is_public and self.scheduled_at is None:
            raise ValueError("scheduled_at is required when is_public is true")
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

    scheduled_at / open_registration / max_participants / private_dag / deathless: SETUP only.
    is_public: editable at any status.
    late_join_window_minutes: SETUP only.
    race_duration_minutes: SETUP, or RUNNING to extend (never shorten).
    custom_rules: SETUP or RUNNING only; blank/whitespace is stored as null.
    """

    scheduled_at: datetime | None = None
    is_public: bool | None = None
    open_registration: bool | None = None
    max_participants: int | None = None
    late_join_window_minutes: int | None = None
    race_duration_minutes: int | None = None
    private_dag: bool | None = None
    deathless: bool | None = None
    custom_rules: str | None = Field(default=None, max_length=1000)


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


class DownloadTicketResponse(BaseModel):
    """Short-lived signed ticket for a native (header-less) pack download."""

    ticket: str


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


class UserDailyStreakStats(BaseModel):
    """Public-facing snapshot of a user's daily-seed streak state."""

    current: int
    best: int
    freeze_count: int

    @classmethod
    def from_user(cls, user: Any) -> "UserDailyStreakStats":
        return cls(
            current=user.daily_current_streak,
            best=user.daily_best_streak,
            freeze_count=user.daily_freeze_count,
        )


class UserStatsResponse(BaseModel):
    """Aggregated user statistics."""

    race_count: int  # terminal-played regular races (FINISHED or ABANDONED with igt > 0)
    daily_count: int  # qualifying daily participations (len(zone_history) >= 2)
    training_count: int
    organized_count: int
    casted_count: int
    weekly: UserStatsWeekly
    daily_streak: UserDailyStreakStats


class PoolTypeStatsResponse(BaseModel):
    """Stats for one type (race or training) in a pool."""

    runs: int
    best_time_ms: int | None = None


class UserPoolStatsEntry(BaseModel):
    """Per-pool stats for a user."""

    pool_name: str
    pool_display_name: str | None = None
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
    mod_version: str | None = None
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
    mod_version: str | None = None


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
    is_mod_connected: bool = False
    mod_version: str | None = None


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
    daily_points: int | None = None


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
    pool_display_name: str | None = None
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
    deathless: bool = False
    custom_rules: str | None = None
    daily_date: date | None = None
    exclude_from_stats: bool = False
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
    event_id: UUID | None = None
    event_slot: str | None = None


class PoolConfig(BaseModel):
    name: str | None = None
    type: str = "race"
    sort_order: int = 99
    estimated_duration: str | None = None
    description: str | None = None
    rules: str | None = None
    layers_count: int | None = None
    final_tier: int | None = None
    starting_runes: int | None = None
    starting_upgrades: list[str] | None = None
    starting_items: list[str] | None = None
    care_package: bool | None = None
    weapon_upgrade: int | None = None
    care_package_items: list[str] | None = None
    items_randomized: bool | None = None
    auto_upgrade_weapons: bool | None = None
    auto_equip: bool | None = None
    remove_requirements: bool | None = None
    major_boss_ratio: str | None = None
    randomize_bosses: str | None = None
    difficulty_curve: str | None = None
    nerf_gargoyles: bool | None = None
    nerf_malenia: bool | None = None
    allcraft: bool | None = None
    sentry_torch_shop: bool | None = None

    @model_validator(mode="before")
    @classmethod
    def _derive_layers_count_from_legacy(cls, data: Any) -> Any:
        # Pool.config rows persisted before the speedfog layers_count refactor
        # carry min_layers/max_layers instead. Derive layers_count from the
        # upper bound so the field is populated until the next pool scan
        # rewrites the JSON in-place.
        if isinstance(data, dict) and data.get("layers_count") is None:
            legacy_max = data.get("max_layers")
            if legacy_max is not None:
                data = {**data, "layers_count": legacy_max}
        return data


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
    pool_display_name: str | None = None
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
    deathless: bool = False
    custom_rules: str | None = None
    daily_date: date | None = None
    exclude_from_stats: bool = False
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
    qualifies: bool  # True iff len(zone_history) >= 2 on the participant row


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
    freeze_protected: bool = False
    deathless: bool = False


class DailyWeekResponse(BaseModel):
    """Response for the daily week grid endpoint."""

    week_start: date
    today: date
    days: list[DailyWeekDay]
    has_earlier: bool
    my_streak: UserDailyStreakStats | None = None
    winners: list["WinnerSummary"] | None = None


class WeeklyLeaderboardUser(BaseModel):
    """User identity carried by weekly-leaderboard rows."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    twitch_username: str
    twitch_display_name: str | None = None
    twitch_avatar_url: str | None = None
    equipped_badge_id: str | None = None
    equipped_name_template_id: str | None = None
    equipped_phantom_skin_id: str | None = None


class WeeklyLeaderboardEntry(BaseModel):
    rank: int
    user: WeeklyLeaderboardUser
    total_points: int
    dailies_played: int
    total_deaths: int
    weapon_combos: list[dict[str, object]] = []


class WeeklyLeaderboardResponse(BaseModel):
    week_starting: date
    week_ending: date
    dailies_total: int
    entries: list[WeeklyLeaderboardEntry]


class WinnerSummary(BaseModel):
    """Identity + total points of a weekly champion (or co-champion)."""

    user: WeeklyLeaderboardUser
    total_points: int


# Resolve the forward reference to WinnerSummary in DailyWeekResponse.
DailyWeekResponse.model_rebuild()


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
    pool_display_name: str | None = None
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


class OverviewKpis(BaseModel):
    total_races: int
    active_players: int
    total_deaths: int
    hours_raced: float


class OverviewWeekly(BaseModel):
    weeks: list[str]
    races: list[int]
    active_users: list[int]
    deaths: list[int]
    hours: list[float]


class StatsOverviewResponse(BaseModel):
    kpis: OverviewKpis
    weekly: OverviewWeekly


class HeatmapResponse(BaseModel):
    timezone: str
    grid: list[list[int]]
    weeks: int


class ZoneStatEntry(BaseModel):
    node_id: str
    display_name: str
    type: str
    total_deaths: int
    avg_deaths_per_visit: float


class ZoneBacktrackEntry(BaseModel):
    node_id: str
    display_name: str
    type: str
    backtrack_count: int
    # Share of visits ending in a turn-away, bounded to [0, 1].
    backtrack_rate: float


class ZoneTimeEntry(BaseModel):
    node_id: str
    display_name: str
    type: str
    median_time_ms: int
    # Number of participants whose clear time feeds the median (one total
    # per participant, not one per visit).
    players: int


class ZoneStatsResponse(BaseModel):
    deadliest: list[ZoneStatEntry]
    most_backtracked: list[ZoneBacktrackEntry]
    slowest: list[ZoneTimeEntry]
    fastest: list[ZoneTimeEntry]


class ZoneIndexEntry(BaseModel):
    node_id: str
    display_name: str
    type: str
    visits: int
    median_time_ms: int
    # Fastest participant clear (min of the same cleared totals the median
    # is computed from); 0 when nobody cleared the zone in the window.
    fastest_time_ms: int
    avg_deaths_per_visit: float
    backtrack_rate: float
    zones: list[str]


class ZoneIndexResponse(BaseModel):
    zones: list[ZoneIndexEntry]


class ZoneDetailResponse(BaseModel):
    node_id: str
    display_name: str
    type: str
    visits: int
    race_count: int
    median_time_ms: int | None
    # Fastest participant clear; None whenever median_time_ms is None.
    fastest_time_ms: int | None
    avg_deaths_per_visit: float
    backtrack_rate: float
    zones: list[str]


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


class WeaponCatalogueEntry(BaseModel):
    """OpenAPI schema for weapon catalogue entries.

    Not wired as ``response_model`` today (the handler returns a raw dict
    keyed by weapon ID string). Provided for documentation completeness and
    reuse when locale-aware variants ship.
    """

    name: str
    wep_type: int


class WeaponComboStat(BaseModel):
    ids: list[int]
    total_ticks: int
    race_count: int
    player_count: int
    top_player_username: str | None = None
    top_player_display_name: str | None = None
    top_player_avatar_url: str | None = None


class WeaponStatsResponse(BaseModel):
    combos: list[WeaponComboStat]


# =============================================================================
# Events
# =============================================================================

EVENT_PHASES: tuple[str, ...] = ("upcoming", "qualifier", "cut", "playoffs", "finished")


class EventMode(BaseModel):
    key: str = Field(min_length=1, max_length=50)
    label: str = Field(min_length=1, max_length=50)


class EventFact(BaseModel):
    """One tile of the format block: a small caps title over one line per entry."""

    title: str = Field(min_length=1, max_length=40)
    lines: list[str] = Field(min_length=1, max_length=4)

    @model_validator(mode="after")
    def _check_text(self) -> "EventFact":
        if not self.title.strip():
            raise ValueError("title must not be blank")
        if any(not line.strip() or len(line) > 60 for line in self.lines):
            raise ValueError("each fact line is 1 to 60 characters")
        return self


class EventStage(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    key: str = Field(min_length=1, max_length=30)
    label: str = Field(min_length=1, max_length=60)
    kind: Literal["semi", "newcomers", "final"]
    date: datetime
    races: int = Field(ge=1, le=5)
    seeds: list[int] | None = None
    from_: list[str] | None = Field(default=None, alias="from")
    advance: int | None = Field(default=None, ge=1, le=3)
    size: int | None = Field(default=None, ge=2, le=8)
    modes: list[str] = []

    @model_validator(mode="after")
    def _check_kind_fields(self) -> "EventStage":
        if self.date.tzinfo is None:
            raise ValueError("date must be timezone-aware")
        if self.kind == "semi":
            if not self.seeds or any(s < 1 for s in self.seeds):
                raise ValueError("a semi stage needs positive seeds")
            if len(set(self.seeds)) != len(self.seeds):
                raise ValueError("seeds must be distinct")
        if self.kind == "final" and (not self.from_ or self.advance is None):
            raise ValueError("a final stage needs from and advance")
        if self.kind == "newcomers" and self.size is None:
            raise ValueError("a newcomers stage needs size")
        return self


class EventConfig(BaseModel):
    modes: list[EventMode] = Field(min_length=1, max_length=6)
    seeds_per_mode: int = Field(default=2, ge=1, le=4)
    stages: list[EventStage] = []
    rules: list[str] = []
    playoff_rules: list[str] = []
    facts: list[EventFact] | None = Field(default=None, max_length=8)
    phase_override: str | None = None
    announced_at: datetime | None = None

    @model_validator(mode="after")
    def _check_structure(self) -> "EventConfig":
        keys = [m.key for m in self.modes]
        if len(set(keys)) != len(keys):
            raise ValueError("mode keys must be unique")
        stage_keys = [s.key for s in self.stages]
        if len(set(stage_keys)) != len(stage_keys):
            raise ValueError("stage keys must be unique")
        semi_keys = {s.key for s in self.stages if s.kind == "semi"}
        semi_seeds = [seed for s in self.stages if s.kind == "semi" for seed in (s.seeds or [])]
        duplicated_seeds = sorted({seed for seed in semi_seeds if semi_seeds.count(seed) > 1})
        if duplicated_seeds:
            raise ValueError(
                f"seeds must be distinct across semi stages, duplicated: {duplicated_seeds}"
            )
        # The newcomers' group starts after the largest seed, so a gap would
        # drop those ladder positions from every playoff group at once; and the
        # page reads the cut off the semis' own field sizes, which a gap makes
        # a smaller number than the positions the semis actually reach into.
        missing = sorted(set(range(1, len(semi_seeds) + 1)) - set(semi_seeds))
        if missing:
            raise ValueError(
                f"seeds must cover the ladder from 1 without a gap, missing: {missing}"
            )
        for stage in self.stages:
            if stage.kind == "final":
                unknown = [k for k in (stage.from_ or []) if k not in semi_keys]
                if unknown:
                    raise ValueError(f"from must name semi stages, got {unknown}")
        # The announcement is the newcomer cut. A newcomers' final draws its
        # field from that cut, so it must be an explicit date, never the
        # timeline's display default.
        if self.announced_at is None and any(s.kind == "newcomers" for s in self.stages):
            raise ValueError("a newcomers stage needs announced_at")
        dates = [s.date for s in self.stages]
        if any(b <= a for a, b in zip(dates, dates[1:], strict=False)):
            raise ValueError("stage dates must be ascending")
        if any(len(r) > 300 for r in self.rules + self.playoff_rules):
            raise ValueError("each rule is at most 300 characters")
        if self.phase_override is not None and self.phase_override not in EVENT_PHASES:
            raise ValueError(f"phase_override must be one of {EVENT_PHASES}")
        if self.announced_at is not None and self.announced_at.tzinfo is None:
            raise ValueError("announced_at must be timezone-aware")
        return self

    def mode_keys(self) -> list[str]:
        return [m.key for m in self.modes]

    def stage(self, key: str) -> EventStage | None:
        return next((s for s in self.stages if s.key == key), None)

    def final_stage(self) -> EventStage | None:
        return next((s for s in self.stages if s.kind == "final"), None)


class EventTimelineStopResponse(BaseModel):
    key: str
    label: str
    date: datetime
    kind: str


class EventMyResultResponse(BaseModel):
    status: Literal["not_played", "joined", "playing", "done"]
    # ``done`` covers a finished run and an abandoned one; the page shows DNF
    # for the latter, which still holds a rank and points below the finishers.
    finished: bool = False
    rank: int | None = None
    igt_ms: int | None = None
    points: int | None = None
    provisional: bool = False


class EventQualifierRaceResponse(BaseModel):
    slot: str
    mode: str
    index: int
    race: RaceResponse
    closes_at: datetime | None
    my_result: EventMyResultResponse | None


class EventLadderEntryResponse(BaseModel):
    rank: int | None
    user: UserResponse
    newcomer: bool
    mode_points: dict[str, int | None]
    total: int | None
    modes_scored: int
    igt_total: int
    provisional: bool


class EventLadderResponse(BaseModel):
    provisional: bool
    # Runners with at least one scoring run.
    entered: int
    ranked_count: int
    # Signed-up runners listed without a run; zero once the event can no longer be joined.
    signed_up: int
    entries: list[EventLadderEntryResponse]


class EventQualifiedSlotResponse(BaseModel):
    seed: int | None
    user: UserResponse | None
    newcomer: bool
    note: str | None


class EventQualifiedGroupResponse(BaseModel):
    stage_key: str
    label: str
    entries: list[EventQualifiedSlotResponse]


class EventQualifiedResponse(BaseModel):
    provisional: bool
    groups: list[EventQualifiedGroupResponse]


class EventStageRaceResponse(BaseModel):
    slot: str
    index: int
    race: RaceResponse


class EventWeaponResponse(BaseModel):
    id: int
    name: str


class EventStageEntryResponse(BaseModel):
    user: UserResponse
    newcomer: bool
    points: int
    igt_total: int
    advances: bool
    # The weapon the runner carried the longest over every event race they entered.
    signature_weapon: EventWeaponResponse | None = None


class EventFieldSlotResponse(BaseModel):
    user: UserResponse | None
    label: str


class EventStageResponse(BaseModel):
    key: str
    label: str
    kind: str
    date: datetime
    races_expected: int
    complete: bool
    modes: list[str]
    races: list[EventStageRaceResponse]
    results: list[EventStageEntryResponse]
    field: list[EventFieldSlotResponse]


class EventNextStageResponse(BaseModel):
    key: str
    label: str
    date: datetime


class EventDetailResponse(BaseModel):
    slug: str
    name: str
    partner_name: str | None
    partner_url: str | None
    partner_logo_url: str | None
    starts_at: datetime
    qualifier_ends_at: datetime
    ends_at: datetime
    newcomer_threshold: int
    phase: str
    ladder_final: bool
    my_signup: bool
    modes: list[EventMode]
    seeds_per_mode: int
    rules: list[str]
    playoff_rules: list[str]
    facts: list[EventFact] | None
    timeline: list[EventTimelineStopResponse]
    qualifier_races: list[EventQualifierRaceResponse]
    ladder: EventLadderResponse
    qualified: EventQualifiedResponse
    stages: list[EventStageResponse]
    current_stage_key: str | None
    live_race: RaceResponse | None
    next_stage: EventNextStageResponse | None


class EventUpsertRequest(BaseModel):
    slug: str = Field(min_length=1, max_length=50, pattern=r"^[a-z0-9-]+$")
    name: str = Field(min_length=1, max_length=200)
    partner_name: str | None = Field(default=None, max_length=100)
    partner_url: str | None = Field(default=None, max_length=500)
    partner_logo_url: str | None = Field(default=None, max_length=500)
    starts_at: datetime
    qualifier_ends_at: datetime
    ends_at: datetime
    newcomer_threshold: int = Field(default=5, ge=0, le=100)
    config: EventConfig

    @model_validator(mode="after")
    def _check_dates(self) -> "EventUpsertRequest":
        for field_name in ("starts_at", "qualifier_ends_at", "ends_at"):
            if getattr(self, field_name).tzinfo is None:
                raise ValueError(f"{field_name} must be timezone-aware")
        if not self.starts_at < self.qualifier_ends_at:
            raise ValueError("starts_at must be before qualifier_ends_at")
        # The announcement is the newcomer cut: at or after the opening, the
        # qualifier's own runs would count towards it.
        if self.config.announced_at is not None and self.config.announced_at >= self.starts_at:
            raise ValueError("announced_at must be before starts_at")
        if self.config.stages:
            if self.qualifier_ends_at > self.config.stages[0].date:
                raise ValueError("qualifier_ends_at must not be after the first stage date")
            if self.config.stages[-1].date >= self.ends_at:
                raise ValueError("ends_at must be after the last stage date")
        elif self.qualifier_ends_at >= self.ends_at:
            raise ValueError("ends_at must be after qualifier_ends_at")
        return self


class AdminEventResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    slug: str
    name: str
    partner_name: str | None
    partner_url: str | None
    partner_logo_url: str | None
    starts_at: datetime
    qualifier_ends_at: datetime
    ends_at: datetime
    newcomer_threshold: int
    config: dict[str, Any]
    created_at: datetime
    phase: str
    # Set when the stored config no longer validates, so the tab that repairs
    # the document can say what is wrong with it.
    config_error: str | None = None
    attached: dict[str, UUID]


class AttachRaceToEventRequest(BaseModel):
    event_id: UUID | None = None
    slot: str | None = Field(default=None, max_length=50)
