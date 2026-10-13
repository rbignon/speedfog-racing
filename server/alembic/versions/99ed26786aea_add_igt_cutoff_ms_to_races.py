"""add igt_cutoff_ms to races

Revision ID: 99ed26786aea
Revises: b8e2f4a6c1d3
Create Date: 2026-10-13 13:57:41.324289

A race can carry the in-game time its runs must finish by; event playoff
races set it from their finishes. NULL everywhere else.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "99ed26786aea"
down_revision: str | None = "b8e2f4a6c1d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("races", sa.Column("igt_cutoff_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "igt_cutoff_ms")
