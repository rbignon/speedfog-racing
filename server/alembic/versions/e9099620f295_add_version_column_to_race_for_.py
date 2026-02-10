"""add version column to race for optimistic locking

Revision ID: e9099620f295
Revises: 30abc306ca1a
Create Date: 2026-02-10 15:49:38.025381

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9099620f295"
down_revision: str | None = "30abc306ca1a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("races", sa.Column("version", sa.Integer(), server_default="1", nullable=False))


def downgrade() -> None:
    op.drop_column("races", "version")
