"""add daily streak

Revision ID: b28f8a846049
Revises: e19ed46884b0
Create Date: 2026-05-12 16:37:56.005321

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b28f8a846049"
down_revision: str | None = "e19ed46884b0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "daily_current_streak",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "daily_best_streak",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column(
            "daily_freeze_count",
            sa.Integer(),
            server_default="0",
            nullable=False,
        ),
    )
    op.add_column(
        "users",
        sa.Column("daily_last_qualifying_date", sa.Date(), nullable=True),
    )

    op.create_check_constraint(
        "ck_users_daily_freeze_count_range",
        "users",
        "daily_freeze_count >= 0 AND daily_freeze_count <= 2",
    )
    op.create_check_constraint(
        "ck_users_daily_current_streak_nonneg",
        "users",
        "daily_current_streak >= 0",
    )
    op.create_check_constraint(
        "ck_users_daily_best_ge_current",
        "users",
        "daily_best_streak >= daily_current_streak",
    )

    op.create_table(
        "daily_streak_freezes",
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("daily_date", sa.Date(), nullable=False),
        sa.Column(
            "consumed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("user_id", "daily_date"),
    )

    # Backfill of historical streak state happens in a follow-up data
    # migration that runs the synchronous walk over participations.
    # Kept separate from the schema migration so this revision applies
    # cleanly even before the streak service module exists.


def downgrade() -> None:
    op.drop_table("daily_streak_freezes")

    op.drop_constraint("ck_users_daily_best_ge_current", "users", type_="check")
    op.drop_constraint("ck_users_daily_current_streak_nonneg", "users", type_="check")
    op.drop_constraint("ck_users_daily_freeze_count_range", "users", type_="check")

    op.drop_column("users", "daily_last_qualifying_date")
    op.drop_column("users", "daily_freeze_count")
    op.drop_column("users", "daily_best_streak")
    op.drop_column("users", "daily_current_streak")
