"""add discord_notified_at to training_sessions

Revision ID: 6f150ab7d804
Revises: 32683b2d0160
Create Date: 2026-03-26 18:03:58.562690

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6f150ab7d804"
down_revision: str | None = "32683b2d0160"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "training_sessions",
        sa.Column("discord_notified_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("training_sessions", "discord_notified_at")
