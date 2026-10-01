"""add debug_flags to participants

Revision ID: e8b3d5f1a7c2
Revises: 4f7c2a9d1e6b
Create Date: 2026-10-01 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8b3d5f1a7c2"
down_revision: str | None = "4f7c2a9d1e6b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("debug_flags", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("participants", "debug_flags")
