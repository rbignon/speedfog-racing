"""replace late-join absolute timestamps with relative durations

Revision ID: a4e2b1c5d7f3
Revises: db417ce6de90
Create Date: 2026-04-21 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a4e2b1c5d7f3"
down_revision: str | None = "db417ce6de90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("races", "race_ends_at")
    op.drop_column("races", "registration_closes_at")
    op.add_column("races", sa.Column("late_join_window_minutes", sa.Integer(), nullable=True))
    op.add_column("races", sa.Column("race_duration_minutes", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "race_duration_minutes")
    op.drop_column("races", "late_join_window_minutes")
    op.add_column(
        "races",
        sa.Column("registration_closes_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "races",
        sa.Column("race_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
