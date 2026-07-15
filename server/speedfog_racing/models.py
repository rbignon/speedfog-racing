"""Database models for SpeedFog Racing."""

import enum
import secrets
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speedfog_racing.database import Base


class UserRole(enum.StrEnum):
    """User roles for authorization."""

    USER = "user"
    ORGANIZER = "organizer"
    ADMIN = "admin"
    SYSTEM = "system"


class RaceStatus(enum.Enum):
    """Race lifecycle status."""

    SETUP = "setup"  # Race created, accepting participants, not yet started
    RUNNING = "running"  # Race in progress
    FINISHED = "finished"  # Race completed


class ParticipantStatus(enum.Enum):
    """Participant status within a race."""

    REGISTERED = "registered"  # Signed up
    READY = "ready"  # Mod connected, ready to start
    PLAYING = "playing"  # Currently racing
    FINISHED = "finished"  # Completed the race
    ABANDONED = "abandoned"  # Left the race


class SeedStatus(enum.Enum):
    """Seed availability status."""

    AVAILABLE = "available"
    CONSUMED = "consumed"
    DISCARDED = "discarded"
    REPORTED = "reported"


class TrainingSessionStatus(enum.Enum):
    """Training session lifecycle status."""

    ACTIVE = "active"
    FINISHED = "finished"
    ABANDONED = "abandoned"
    CANCELLED = "cancelled"


class ChatChannel(enum.StrEnum):
    """Chat channel types."""

    PARTICIPANTS = "participants"
    PUBLIC = "public"


def generate_token() -> str:
    """Generate a secure random token."""
    return secrets.token_urlsafe(32)


class User(Base):
    """User account linked to Twitch."""

    __tablename__ = "users"
    __table_args__ = (
        CheckConstraint(
            "daily_freeze_count >= 0 AND daily_freeze_count <= 2",
            name="ck_users_daily_freeze_count_range",
        ),
        CheckConstraint(
            "daily_current_streak >= 0",
            name="ck_users_daily_current_streak_nonneg",
        ),
        CheckConstraint(
            "daily_best_streak >= daily_current_streak",
            name="ck_users_daily_best_ge_current",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    twitch_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    twitch_username: Mapped[str] = mapped_column(String(100), nullable=False)
    twitch_display_name: Mapped[str | None] = mapped_column(String(100))
    twitch_avatar_url: Mapped[str | None] = mapped_column(String(500))
    api_token: Mapped[str | None] = mapped_column(
        String(100), unique=True, nullable=True, default=generate_token
    )
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.ORGANIZER)
    locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    overlay_settings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    feedback_prompted_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    equipped_badge_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    equipped_name_template_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    equipped_phantom_skin_id: Mapped[str | None] = mapped_column(String(50), nullable=True)
    daily_current_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    daily_best_streak: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    daily_freeze_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    daily_last_qualifying_date: Mapped[date | None] = mapped_column(Date, nullable=True)

    # Relationships
    organized_races: Mapped[list["Race"]] = relationship(back_populates="organizer")
    participations: Mapped[list["Participant"]] = relationship(back_populates="user")
    caster_roles: Mapped[list["Caster"]] = relationship(back_populates="user")


class Pool(Base):
    """A curated pool of seeds (e.g. "standard", "sprint").

    Runtime state (``enabled``, ``last_scanned_at``) lives here. The
    immutable pool definition is loaded from the on-disk ``config.toml`` at
    scan time and cached in ``config``.
    """

    __tablename__ = "pools"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, server_default="true")
    config: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False, default=dict)
    last_scanned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    seeds: Mapped[list["Seed"]] = relationship(back_populates="pool")


class DailySeedSchedule(Base):
    """Weekday to pool rotation for Daily Seeds.

    Monday=0, Sunday=6 (Python ``date.weekday()`` convention). The daily
    creation loop picks the row matching ``today.weekday()`` to decide
    which pool the next Daily Seed should draw from.
    """

    __tablename__ = "daily_seed_schedule"

    weekday: Mapped[int] = mapped_column(Integer, primary_key=True)
    pool_name: Mapped[str] = mapped_column(String(50), ForeignKey("pools.name"), nullable=False)

    pool: Mapped["Pool"] = relationship(lazy="joined")


class Seed(Base):
    """A SpeedFog seed available for racing."""

    __tablename__ = "seeds"
    __table_args__ = (
        # Seed selection (pool + availability) in seed_service.
        Index("ix_seeds_pool_status", "pool_name", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seed_number: Mapped[str] = mapped_column(String(50), nullable=False)
    pool_name: Mapped[str] = mapped_column(String(50), ForeignKey("pools.name"), nullable=False)
    graph_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    total_layers: Mapped[int] = mapped_column(Integer, nullable=False)
    difficulty_score: Mapped[float] = mapped_column(default=0.0, server_default="0.0")
    folder_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[SeedStatus] = mapped_column(Enum(SeedStatus), default=SeedStatus.AVAILABLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    reported_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reported_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Relationships
    # ``lazy="joined"`` so that fetching a Seed always brings its Pool in the
    # same query. Callers therefore never need to add
    # ``selectinload(Seed.pool)``, and sync helpers can read ``seed.pool``
    # freely without tripping the async lazy-load error.
    pool: Mapped["Pool"] = relationship(back_populates="seeds", lazy="joined")
    races: Mapped[list["Race"]] = relationship(back_populates="seed")
    reported_by: Mapped["User | None"] = relationship(foreign_keys=[reported_by_id])


class Race(Base):
    """A race event with participants."""

    __tablename__ = "races"
    __table_args__ = (
        # Organizer dashboard (races listed by organizer).
        Index("ix_races_organizer", "organizer_id"),
        # Running-race lookups (WS handlers, inactivity monitor).
        Index("ix_races_status", "status"),
        # Date-range filters in analytics and stats endpoints.
        Index("ix_races_started_at", "started_at"),
        # At most one Daily Seed race per UTC day; partial unique index so
        # regular races (daily_date IS NULL) are unaffected.
        Index(
            "uq_races_daily_date",
            "daily_date",
            unique=True,
            postgresql_where=text("daily_date IS NOT NULL"),
            sqlite_where=text("daily_date IS NOT NULL"),
        ),
        Index("ix_races_daily_date", "daily_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    organizer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    seed_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seeds.id"), nullable=True
    )
    status: Mapped[RaceStatus] = mapped_column(Enum(RaceStatus), default=RaceStatus.SETUP)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # Effective gameplay start: when the race transitions to RUNNING, the
    # /start endpoint sets this to ``now + countdown_seconds`` so the
    # countdown window does not eat into the configured race duration.
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    seeds_released_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    is_public: Mapped[bool] = mapped_column(
        Boolean, default=True, server_default="1", nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, server_default="1", nullable=False)
    open_registration: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    max_participants: Mapped[int | None] = mapped_column(Integer, nullable=True)
    discord_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    malenia_event_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    late_join_window_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    race_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    custom_rules: Mapped[str | None] = mapped_column(Text, nullable=True)
    private_dag: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )
    # Daily Seed marker: NULL for regular races, the UTC rotation date for
    # the one race auto-created per day. Combined with the partial unique
    # index above, this enforces at most one daily per day.
    daily_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    # Skip ELO updates for this race (Daily Seeds, calibration runs, etc.).
    exclude_from_elo: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="0", nullable=False
    )

    # Relationships
    organizer: Mapped["User"] = relationship(back_populates="organized_races")
    seed: Mapped["Seed | None"] = relationship(back_populates="races")
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="race", cascade="all, delete-orphan"
    )
    casters: Mapped[list["Caster"]] = relationship(
        back_populates="race", cascade="all, delete-orphan"
    )
    invites: Mapped[list["Invite"]] = relationship(
        back_populates="race", cascade="all, delete-orphan"
    )


class Participant(Base):
    """A user participating in a race."""

    __tablename__ = "participants"
    __table_args__ = (
        UniqueConstraint("race_id", "user_id", name="uq_participants_race_user"),
        # Per-user trait recomputation and abandon checks.
        Index("ix_participants_user_race_status", "user_id", "race_id", "status"),
        # Leaderboard lookups and Race.participants selectinload cascades.
        Index("ix_participants_race_user", "race_id", "user_id"),
        # Inactivity monitor (runs every 60s) filters by status + last_igt_change_at.
        Index("ix_participants_status_igt_change", "status", "last_igt_change_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("races.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    mod_token: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, default=generate_token
    )

    # Race progress
    current_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    current_layer: Mapped[int] = mapped_column(Integer, default=0)
    igt_ms: Mapped[int] = mapped_column(Integer, default=0)
    death_count: Mapped[int] = mapped_column(Integer, default=0)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_igt_change_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    status: Mapped[ParticipantStatus] = mapped_column(
        Enum(ParticipantStatus), default=ParticipantStatus.REGISTERED
    )
    color_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    # ``none_as_null=True``: Python ``None`` maps to SQL NULL on write,
    # not JSON ``null``. Without this, any assignment that resets the
    # history (e.g. daily reroll) would leave the column holding the JSON
    # value ``null`` and crash predicates like ``json_array_length`` on
    # PostgreSQL.
    zone_history: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    # IGT at first entry into each layer, keyed by layer number (string).
    # Maintained at runtime as current_layer advances; read by
    # sort_leaderboard for gap computation.
    layer_entry_igts: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )
    # Used by inactivity_monitor to scope the no-show timeout per-participant
    # (late-joiners must not be abandoned based on Race.started_at alone).
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    # Relationships
    race: Mapped["Race"] = relationship(back_populates="participants")
    user: Mapped["User"] = relationship(back_populates="participations")


class DailyStreakFreeze(Base):
    """One row per freeze-protected daily date for a user.

    Written by the daily-close evaluator and by the backfill when a freeze
    is consumed to skip a missed day. Read by ``/api/daily/week`` to
    decorate cells with the ``freeze`` strip variant.
    """

    __tablename__ = "daily_streak_freezes"

    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    daily_date: Mapped[date] = mapped_column(Date, primary_key=True)
    consumed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    user: Mapped["User"] = relationship()


class FeedbackSource(enum.Enum):
    POST_FIRST_RACE = "post_first_race"
    USER_MENU = "user_menu"


class Feedback(Base):
    """User feedback: CSAT rating + optional comment."""

    __tablename__ = "feedback"
    __table_args__ = (
        CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating_range"),
        Index("ix_feedback_created_at", "created_at"),
        Index("ix_feedback_user_id", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    rating: Mapped[int] = mapped_column(Integer, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    source: Mapped[FeedbackSource] = mapped_column(
        Enum(FeedbackSource, name="feedback_source"), nullable=False
    )
    race_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("races.id"), nullable=True
    )
    races_played_at_feedback: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    user: Mapped["User"] = relationship()
    race: Mapped["Race | None"] = relationship()


class Caster(Base):
    """A user with caster role for a race (can see the DAG but doesn't play)."""

    __tablename__ = "casters"
    __table_args__ = (UniqueConstraint("race_id", "user_id", name="uq_casters_race_user"),)

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("races.id"), nullable=False
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Relationships
    race: Mapped["Race"] = relationship(back_populates="casters")
    user: Mapped["User"] = relationship(back_populates="caster_roles")


class Invite(Base):
    """Invitation token for users without accounts."""

    __tablename__ = "invites"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("races.id"), nullable=False
    )
    token: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, default=generate_token
    )
    twitch_username: Mapped[str] = mapped_column(String(100), nullable=False)
    accepted: Mapped[bool] = mapped_column(default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    race: Mapped["Race"] = relationship(back_populates="invites")


class TrainingSession(Base):
    """A solo training session."""

    __tablename__ = "training_sessions"
    __table_args__ = (
        # User profile page (sessions filtered by status).
        Index("ix_training_sessions_user_status", "user_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    seed_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seeds.id"), nullable=False
    )
    mod_token: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, default=generate_token
    )
    status: Mapped[TrainingSessionStatus] = mapped_column(
        Enum(TrainingSessionStatus), default=TrainingSessionStatus.ACTIVE
    )
    igt_ms: Mapped[int] = mapped_column(Integer, default=0)
    death_count: Mapped[int] = mapped_column(Integer, default=0)
    # ``none_as_null=True``: Python ``None`` maps to SQL NULL on write,
    # not JSON ``null``. Without this, any assignment that resets the
    # history (e.g. daily reroll) would leave the column holding the JSON
    # value ``null`` and crash predicates like ``json_array_length`` on
    # PostgreSQL.
    zone_history: Mapped[list[dict[str, Any]] | None] = mapped_column(
        JSON(none_as_null=True), nullable=True
    )
    current_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    discord_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship()
    seed: Mapped["Seed"] = relationship()


class PlayerTraitScores(Base):
    __tablename__ = "player_trait_scores"

    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), primary_key=True)
    dominant_trait: Mapped[str | None] = mapped_column(nullable=True)
    dominant_description: Mapped[str | None] = mapped_column(nullable=True)
    rusher: Mapped[int] = mapped_column(default=0)
    cautious: Mapped[int] = mapped_column(default=0)
    resilient: Mapped[int] = mapped_column(default=0)
    rage_quitter: Mapped[int] = mapped_column(default=0)
    explorer: Mapped[int] = mapped_column(default=0)
    pathfinder: Mapped[int] = mapped_column(default=0)
    boss_slayer: Mapped[int] = mapped_column(default=0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class ChatMessage(Base):
    """A persisted chat message in a race channel."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_race_channel_created", "race_id", "channel", "created_at"),
        # User-scoped access (moderation, cascade on user deletion).
        Index("ix_chat_messages_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("races.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[ChatChannel] = mapped_column(Enum(ChatChannel), nullable=False)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=True
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    # Python-side default so each row gets a distinct microsecond stamp at
    # INSERT time. ``server_default=func.now()`` (Postgres ``now()``,
    # SQLite ``CURRENT_TIMESTAMP``) returns the transaction start time, so
    # two messages persisted in the same endpoint shared a timestamp and
    # the leaderboard / chat history ORDER BY had to fall back on the
    # random UUID ``id`` to break ties. The Python callable is invoked
    # once per INSERT, giving stable insertion order.
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(UTC),
        server_default=func.now(),
    )

    race: Mapped["Race"] = relationship()
    user: Mapped["User | None"] = relationship()


def compute_late_join_deadlines(race: Race) -> tuple[datetime | None, datetime | None]:
    """Compute absolute (registration_closes_at, race_ends_at) from stored durations.

    Both deadlines are ``None`` until ``started_at`` is set. Used by REST
    responses and the WebSocket ``RaceInfo`` builder so clients never
    re-derive the math.

    Placed on the model module to stay neutral between ``api.helpers`` and
    ``websocket.schemas`` (both serializers call it; the former additionally
    imports response schemas that would cycle back to websocket.schemas).
    """
    started = race.started_at
    if started is None:
        return None, None
    if started.tzinfo is None:
        started = started.replace(tzinfo=UTC)
    closes = (
        started + timedelta(minutes=race.late_join_window_minutes)
        if race.late_join_window_minutes is not None
        else None
    )
    ends = (
        started + timedelta(minutes=race.race_duration_minutes)
        if race.race_duration_minutes is not None
        else None
    )
    return closes, ends


class BadgeGrant(Base):
    """A grant of a badge to a user. revoked_at IS NULL means currently held."""

    __tablename__ = "badge_grants"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    badge_id: Mapped[str] = mapped_column(String(50), nullable=False)
    granted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        Index("ix_badge_grants_user_id", "user_id"),
        Index(
            "ix_badge_grants_active",
            "badge_id",
            "user_id",
            postgresql_where=text("revoked_at IS NULL"),
            sqlite_where=text("revoked_at IS NULL"),
        ),
    )


class NameTemplateUnlock(Base):
    """A user's permanent unlock of a name template."""

    __tablename__ = "name_template_unlocks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    template_id: Mapped[str] = mapped_column(String(50), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        Index("ix_name_template_unlocks_user_id", "user_id"),
        UniqueConstraint("user_id", "template_id", name="uq_name_template_unlocks_user_template"),
    )


class PhantomSkinUnlock(Base):
    """A user's permanent unlock of a phantom skin."""

    __tablename__ = "phantom_skin_unlocks"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    skin_id: Mapped[str] = mapped_column(String(50), nullable=False)
    unlocked_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reason: Mapped[str | None] = mapped_column(String(200), nullable=True)

    __table_args__ = (
        Index("ix_phantom_skin_unlocks_user_id", "user_id"),
        UniqueConstraint("user_id", "skin_id", name="uq_phantom_skin_unlocks_user_skin"),
    )


class RewardNotification(Base):
    """Pending or dismissed notification surfaced as a dashboard banner."""

    __tablename__ = "reward_notifications"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    reward_id: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    dismissed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (Index("ix_reward_notifications_user_id", "user_id"),)
