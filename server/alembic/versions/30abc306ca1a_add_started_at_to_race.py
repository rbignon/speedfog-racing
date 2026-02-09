"""add_started_at_to_race

Revision ID: 30abc306ca1a
Revises: 8663dfafb132
Create Date: 2026-02-09 16:11:21.130415

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "30abc306ca1a"
down_revision: str | None = "8663dfafb132"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("races", sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "started_at")
