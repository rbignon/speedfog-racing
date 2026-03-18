"""add elo and trait tables

Revision ID: 32683b2d0160
Revises: 1f26595211af
Create Date: 2026-03-18 14:43:40.260879

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "32683b2d0160"
down_revision: str | None = "1f26595211af"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # elo_history table
    op.create_table(
        "elo_history",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("race_id", sa.UUID(as_uuid=True), sa.ForeignKey("races.id"), nullable=False),
        sa.Column("elo_before", sa.Float(), nullable=False),
        sa.Column("elo_after", sa.Float(), nullable=False),
        sa.Column("delta", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_elo_history_user_created",
        "elo_history",
        ["user_id", "created_at"],
    )

    # player_trait_scores table
    op.create_table(
        "player_trait_scores",
        sa.Column("user_id", sa.UUID(as_uuid=True), sa.ForeignKey("users.id"), primary_key=True),
        sa.Column("dominant_trait", sa.String(), nullable=True),
        sa.Column("rusher", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cautious", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("resilient", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("rage_quitter", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("explorer", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("pathfinder", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("boss_slayer", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )

    # New columns on users
    op.add_column(
        "users",
        sa.Column("elo_rating", sa.Float(), nullable=False, server_default="1500.0"),
    )
    op.add_column(
        "users",
        sa.Column("elo_races", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("users", "elo_races")
    op.drop_column("users", "elo_rating")
    op.drop_table("player_trait_scores")
    op.drop_index("ix_elo_history_user_created", table_name="elo_history")
    op.drop_table("elo_history")
