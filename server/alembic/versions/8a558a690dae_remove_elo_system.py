"""remove elo system

Revision ID: 8a558a690dae
Revises: b46282beecdd
Create Date: 2026-07-15 17:55:48.344821

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8a558a690dae"
down_revision: str | None = "b46282beecdd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- schema ---
    op.drop_index("ix_elo_history_user_created", table_name="elo_history")
    op.drop_table("elo_history")
    op.drop_column("users", "elo_rating")
    op.drop_column("users", "elo_races")
    op.alter_column("races", "exclude_from_elo", new_column_name="exclude_from_stats")

    # --- data: repurposed name templates keep their unlocks under new ids ---
    op.execute(
        "UPDATE name_template_unlocks SET template_id = 'daily_crown'"
        " WHERE template_id = 'elo_crown'"
    )
    op.execute(
        "UPDATE name_template_unlocks SET template_id = 'dawnrunner'"
        " WHERE template_id = 'runebearer'"
    )
    op.execute(
        "UPDATE users SET equipped_name_template_id = 'daily_crown'"
        " WHERE equipped_name_template_id = 'elo_crown'"
    )
    op.execute(
        "UPDATE users SET equipped_name_template_id = 'dawnrunner'"
        " WHERE equipped_name_template_id = 'runebearer'"
    )
    op.execute(
        "UPDATE reward_notifications SET reward_id = 'daily_crown'"
        " WHERE reward_id = 'elo_crown' AND kind LIKE 'name_template%'"
    )
    op.execute(
        "UPDATE reward_notifications SET reward_id = 'dawnrunner'"
        " WHERE reward_id = 'runebearer' AND kind LIKE 'name_template%'"
    )

    # --- data: the top1_elo badge no longer exists in the catalog ---
    op.execute("UPDATE users SET equipped_badge_id = NULL WHERE equipped_badge_id = 'top1_elo'")
    op.execute("DELETE FROM badge_grants WHERE badge_id = 'top1_elo'")
    op.execute("DELETE FROM reward_notifications WHERE reward_id = 'top1_elo'")


def downgrade() -> None:
    # Schema shape only; deleted ELO history, badge grants, and notifications
    # are not reconstructable.
    op.execute(
        "UPDATE name_template_unlocks SET template_id = 'elo_crown'"
        " WHERE template_id = 'daily_crown'"
    )
    op.execute(
        "UPDATE name_template_unlocks SET template_id = 'runebearer'"
        " WHERE template_id = 'dawnrunner'"
    )
    op.execute(
        "UPDATE users SET equipped_name_template_id = 'elo_crown'"
        " WHERE equipped_name_template_id = 'daily_crown'"
    )
    op.execute(
        "UPDATE users SET equipped_name_template_id = 'runebearer'"
        " WHERE equipped_name_template_id = 'dawnrunner'"
    )
    op.execute(
        "UPDATE reward_notifications SET reward_id = 'elo_crown'"
        " WHERE reward_id = 'daily_crown' AND kind LIKE 'name_template%'"
    )
    op.execute(
        "UPDATE reward_notifications SET reward_id = 'runebearer'"
        " WHERE reward_id = 'dawnrunner' AND kind LIKE 'name_template%'"
    )
    op.alter_column("races", "exclude_from_stats", new_column_name="exclude_from_elo")
    op.add_column(
        "users",
        sa.Column("elo_rating", sa.Float(), nullable=False, server_default="1500.0"),
    )
    op.add_column(
        "users",
        sa.Column("elo_races", sa.Integer(), nullable=False, server_default="0"),
    )
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
