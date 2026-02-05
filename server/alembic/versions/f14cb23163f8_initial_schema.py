"""initial schema

Revision ID: f14cb23163f8
Revises:
Create Date: 2026-02-05 13:32:39.783093

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f14cb23163f8"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Define enum types - create_type=False because we create them explicitly
userrole = postgresql.ENUM("USER", "ADMIN", name="userrole", create_type=False)
seedstatus = postgresql.ENUM("AVAILABLE", "CONSUMED", name="seedstatus", create_type=False)
racestatus = postgresql.ENUM(
    "DRAFT", "OPEN", "COUNTDOWN", "RUNNING", "FINISHED", name="racestatus", create_type=False
)
participantstatus = postgresql.ENUM(
    "REGISTERED",
    "READY",
    "PLAYING",
    "FINISHED",
    "ABANDONED",
    name="participantstatus",
    create_type=False,
)


def upgrade() -> None:
    # Create enum types first
    userrole.create(op.get_bind(), checkfirst=True)
    seedstatus.create(op.get_bind(), checkfirst=True)
    racestatus.create(op.get_bind(), checkfirst=True)
    participantstatus.create(op.get_bind(), checkfirst=True)

    # Users table
    op.create_table(
        "users",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("twitch_id", sa.String(50), unique=True, nullable=False),
        sa.Column("twitch_username", sa.String(100), nullable=False),
        sa.Column("twitch_display_name", sa.String(100), nullable=True),
        sa.Column("twitch_avatar_url", sa.String(500), nullable=True),
        sa.Column("api_token", sa.String(100), unique=True, nullable=False),
        sa.Column("role", userrole, nullable=False, server_default="USER"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Seeds table
    op.create_table(
        "seeds",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("seed_number", sa.Integer(), nullable=False),
        sa.Column("pool_name", sa.String(50), nullable=False),
        sa.Column("graph_json", postgresql.JSON(), nullable=False),
        sa.Column("total_layers", sa.Integer(), nullable=False),
        sa.Column("folder_path", sa.String(500), nullable=False),
        sa.Column("status", seedstatus, nullable=False, server_default="AVAILABLE"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Races table
    op.create_table(
        "races",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column(
            "organizer_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column(
            "seed_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("seeds.id"),
            nullable=True,
        ),
        sa.Column("status", racestatus, nullable=False, server_default="DRAFT"),
        sa.Column("config", postgresql.JSON(), nullable=False, server_default="{}"),
        sa.Column("scheduled_start", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Participants table
    op.create_table(
        "participants",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "race_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("races.id"),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("mod_token", sa.String(100), unique=True, nullable=False),
        sa.Column("current_zone", sa.String(100), nullable=True),
        sa.Column("current_layer", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("igt_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("death_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("status", participantstatus, nullable=False, server_default="REGISTERED"),
    )

    # Invites table
    op.create_table(
        "invites",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "race_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("races.id"),
            nullable=False,
        ),
        sa.Column("token", sa.String(100), unique=True, nullable=False),
        sa.Column("twitch_username", sa.String(100), nullable=False),
        sa.Column("accepted", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    # Create unique constraint for participants (one registration per user per race)
    op.create_unique_constraint("uq_participants_race_user", "participants", ["race_id", "user_id"])

    # Create indexes for common queries
    op.create_index("ix_races_status", "races", ["status"])
    op.create_index("ix_participants_race_id", "participants", ["race_id"])
    op.create_index("ix_seeds_pool_status", "seeds", ["pool_name", "status"])


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_seeds_pool_status", "seeds")
    op.drop_index("ix_participants_race_id", "participants")
    op.drop_index("ix_races_status", "races")

    # Drop unique constraint
    op.drop_constraint("uq_participants_race_user", "participants", type_="unique")

    # Drop tables in reverse order (respecting FK constraints)
    op.drop_table("invites")
    op.drop_table("participants")
    op.drop_table("races")
    op.drop_table("seeds")
    op.drop_table("users")

    # Drop enum types
    participantstatus.drop(op.get_bind(), checkfirst=True)
    racestatus.drop(op.get_bind(), checkfirst=True)
    seedstatus.drop(op.get_bind(), checkfirst=True)
    userrole.drop(op.get_bind(), checkfirst=True)
