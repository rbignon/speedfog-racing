"""add seeds_released_at to race

Revision ID: 736fc1ba38f3
Revises: 3a3d9111c571
Create Date: 2026-02-19 19:24:11.447148

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "736fc1ba38f3"
down_revision: str | None = "3a3d9111c571"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "races", sa.Column("seeds_released_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("races", "seeds_released_at")
