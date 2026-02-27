"""add exclude_from_stats to training_sessions

Revision ID: afe8e80417ef
Revises: e2bd973f46cb
Create Date: 2026-02-27 15:43:46.782386

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "afe8e80417ef"
down_revision: str | None = "e2bd973f46cb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "training_sessions",
        sa.Column(
            "exclude_from_stats", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )


def downgrade() -> None:
    op.drop_column("training_sessions", "exclude_from_stats")
