"""training session reset count

Revision ID: 50546370bf40
Revises: 051608e6d0ba
Create Date: 2026-11-11 19:30:00.000000

Counts the resets of a Set Seed solo run. The mod saves the event flags the
server has not acknowledged with the run's attempt id (the race object's
``attempt_id``, the reset count for a solo session) and drops those of
another attempt on the next launch: without it, a run reset while the game
was closed would record a fog of the old attempt as a LiveSplit split of the
new one (the server ignores that fog, the new attempt's history being empty).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "50546370bf40"
down_revision: str | None = "051608e6d0ba"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "training_sessions",
        sa.Column("reset_count", sa.Integer(), server_default="0", nullable=False),
    )


def downgrade() -> None:
    op.drop_column("training_sessions", "reset_count")
