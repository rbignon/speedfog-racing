"""Database models for SpeedFog Racing."""

import enum
import secrets
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, UniqueConstraint, func
from sqlalchemy.dialects.postgresql import JSON, UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from speedfog_racing.database import Base


class UserRole(enum.Enum):
    """User roles for authorization."""

    USER = "user"
    ADMIN = "admin"


class RaceStatus(enum.Enum):
    """Race lifecycle status."""

    DRAFT = "draft"  # Race created, not yet open
    OPEN = "open"  # Accepting participants
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
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.USER)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    organized_races: Mapped[list["Race"]] = relationship(back_populates="organizer")
    participations: Mapped[list["Participant"]] = relationship(back_populates="user")
    caster_roles: Mapped[list["Caster"]] = relationship(back_populates="user")


class Seed(Base):
    """A SpeedFog seed available for racing."""

    __tablename__ = "seeds"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    seed_number: Mapped[int] = mapped_column(Integer, nullable=False)
    pool_name: Mapped[str] = mapped_column(String(50), nullable=False)  # "standard", "sprint"
    graph_json: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    total_layers: Mapped[int] = mapped_column(Integer, nullable=False)
    folder_path: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[SeedStatus] = mapped_column(Enum(SeedStatus), default=SeedStatus.AVAILABLE)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    races: Mapped[list["Race"]] = relationship(back_populates="seed")


class Race(Base):
    """A race event with participants."""

    __tablename__ = "races"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    organizer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    seed_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("seeds.id"), nullable=True
    )
    status: Mapped[RaceStatus] = mapped_column(Enum(RaceStatus), default=RaceStatus.DRAFT)
    config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())

    # Relationships
    organizer: Mapped["User"] = relationship(back_populates="organized_races")
    seed: Mapped["Seed | None"] = relationship(back_populates="races")
    participants: Mapped[list["Participant"]] = relationship(
        back_populates="race", cascade="all, delete-orphan"
    )
    casters: Mapped[list["Caster"]] = relationship(
        back_populates="race", cascade="all, delete-orphan"
    )


class Participant(Base):
    """A user participating in a race."""

    __tablename__ = "participants"
    __table_args__ = (UniqueConstraint("race_id", "user_id", name="uq_participants_race_user"),)

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
    status: Mapped[ParticipantStatus] = mapped_column(
        Enum(ParticipantStatus), default=ParticipantStatus.REGISTERED
    )
    color_index: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    has_seed_pack: Mapped[bool] = mapped_column(default=False, server_default="0")
    zone_history: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)

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
    race: Mapped["Race"] = relationship()
