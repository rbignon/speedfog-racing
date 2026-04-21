"""Database models for SpeedFog Racing."""

import enum
import secrets
import uuid
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import (
    Boolean,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speedfog_racing.database import Base


class UserRole(enum.StrEnum):
    """User roles for authorization."""

    USER = "user"
    ORGANIZER = "organizer"
    ADMIN = "admin"


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

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    twitch_id: Mapped[str] = mapped_column(String(50), unique=True, nullable=False)
    twitch_username: Mapped[str] = mapped_column(String(100), nullable=False)
    twitch_display_name: Mapped[str | None] = mapped_column(String(100))
    twitch_avatar_url: Mapped[str | None] = mapped_column(String(500))
    api_token: Mapped[str] = mapped_column(
        String(100), unique=True, nullable=False, default=generate_token
    )
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.ORGANIZER)
    locale: Mapped[str | None] = mapped_column(String(10), nullable=True)
    overlay_settings: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    elo_rating: Mapped[float] = mapped_column(default=1500.0)
    elo_races: Mapped[int] = mapped_column(default=0)

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
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    late_join_window_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    race_duration_minutes: Mapped[int | None] = mapped_column(Integer, nullable=True)
    private_dag: Mapped[bool] = mapped_column(
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
    zone_history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    # IGT at first entry into each layer, keyed by layer number (string).
    # Maintained at runtime as current_layer advances; read by
    # sort_leaderboard for gap computation.
    layer_entry_igts: Mapped[dict[str, int]] = mapped_column(
        JSON, nullable=False, default=dict, server_default="{}"
    )

    # Relationships
    race: Mapped["Race"] = relationship(back_populates="participants")
    user: Mapped["User"] = relationship(back_populates="participations")


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
    zone_history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    current_zone: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    exclude_from_stats: Mapped[bool] = mapped_column(default=False)
    discord_notified_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # Relationships
    user: Mapped["User"] = relationship()
    seed: Mapped["Seed"] = relationship()


class EloHistory(Base):
    __tablename__ = "elo_history"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"), nullable=False)
    race_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("races.id"), nullable=False)
    elo_before: Mapped[float] = mapped_column(nullable=False)
    elo_after: Mapped[float] = mapped_column(nullable=False)
    delta: Mapped[float] = mapped_column(nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (Index("ix_elo_history_user_created", "user_id", "created_at"),)


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
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

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
