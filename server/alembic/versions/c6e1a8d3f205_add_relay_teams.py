"""add relay teams

Revision ID: c6e1a8d3f205
Revises: 5b9c2e7a4d13
Create Date: 2026-11-20 14:00:00.000000

Relay races: races get the team size and the "runners create teams" toggle,
relay_teams holds one row per team (progress, baton, state), participants get
their team, zone count and fresh-save flag. Teams and participants point at
each other, all three keys ON DELETE SET NULL: relay_teams is created first
without its two keys towards participants, the participants columns come
next, and the two keys are added last.

Written by hand: autogenerate needs a database at head.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6e1a8d3f205"
down_revision: str | None = "5b9c2e7a4d13"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The type exists since the initial schema: never created or dropped here.
_PARTICIPANT_STATUS = postgresql.ENUM(
    "REGISTERED",
    "READY",
    "PLAYING",
    "FINISHED",
    "ABANDONED",
    "DISQUALIFIED",
    name="participantstatus",
    create_type=False,
)


def upgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(sa.Column("relay_team_size", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column(
                "relay_runners_create_teams", sa.Boolean(), nullable=False, server_default="1"
            )
        )

    op.create_table(
        "relay_teams",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("race_id", sa.Uuid(), nullable=False),
        sa.Column("name", sa.String(40), nullable=False),
        sa.Column("color_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("placeholder", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("first_runner_id", sa.Uuid(), nullable=True),
        sa.Column("holder_id", sa.Uuid(), nullable=True),
        sa.Column("holder_offline_since", sa.DateTime(timezone=True), nullable=True),
        sa.Column("baton_free", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("status", _PARTICIPANT_STATUS, nullable=False, server_default="REGISTERED"),
        sa.Column("current_zone", sa.String(100), nullable=True),
        sa.Column("current_layer", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("igt_ms", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("death_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_igt_change_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("zone_history", sa.JSON(), nullable=True),
        sa.Column("layer_entry_igts", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("entry_flag_id", sa.Integer(), nullable=True),
        sa.Column("character_state", sa.JSON(), nullable=True),
        sa.Column("character_state_igt_ms", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["race_id"], ["races.id"], name="fk_relay_teams_race_id"),
        sa.PrimaryKeyConstraint("id", name="pk_relay_teams"),
    )
    op.create_index("ix_relay_teams_race", "relay_teams", ["race_id"])

    with op.batch_alter_table("participants") as batch_op:
        batch_op.add_column(sa.Column("relay_team_id", sa.Uuid(), nullable=True))
        batch_op.add_column(
            sa.Column("relay_zones", sa.Integer(), nullable=False, server_default="0")
        )
        batch_op.add_column(
            sa.Column("relay_validated", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.create_foreign_key(
            "fk_participants_relay_team_id",
            "relay_teams",
            ["relay_team_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_index("ix_participants_relay_team", ["relay_team_id"])

    with op.batch_alter_table("relay_teams") as batch_op:
        batch_op.create_foreign_key(
            "fk_relay_teams_first_runner_id",
            "participants",
            ["first_runner_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch_op.create_foreign_key(
            "fk_relay_teams_holder_id",
            "participants",
            ["holder_id"],
            ["id"],
            ondelete="SET NULL",
        )


def downgrade() -> None:
    with op.batch_alter_table("relay_teams") as batch_op:
        batch_op.drop_constraint("fk_relay_teams_holder_id", type_="foreignkey")
        batch_op.drop_constraint("fk_relay_teams_first_runner_id", type_="foreignkey")

    with op.batch_alter_table("participants") as batch_op:
        batch_op.drop_index("ix_participants_relay_team")
        batch_op.drop_constraint("fk_participants_relay_team_id", type_="foreignkey")
        batch_op.drop_column("relay_validated")
        batch_op.drop_column("relay_zones")
        batch_op.drop_column("relay_team_id")

    op.drop_index("ix_relay_teams_race", table_name="relay_teams")
    op.drop_table("relay_teams")

    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("relay_runners_create_teams")
        batch_op.drop_column("relay_team_size")
