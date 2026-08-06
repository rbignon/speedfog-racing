"""add deathless to daily seed schedule

Revision ID: 42520d221730
Revises: b8ecd1b57d3f
Create Date: 2026-08-06 14:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "42520d221730"
down_revision: str | None = "b8ecd1b57d3f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "daily_seed_schedule",
        sa.Column("deathless", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("daily_seed_schedule", "deathless")
