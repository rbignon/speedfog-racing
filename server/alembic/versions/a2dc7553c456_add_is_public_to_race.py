"""add is_public to race

Revision ID: a2dc7553c456
Revises: b2c3d4e5f6a7
Create Date: 2026-02-17 14:02:19.881379

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a2dc7553c456"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("races", sa.Column("is_public", sa.Boolean(), server_default="1", nullable=False))


def downgrade() -> None:
    op.drop_column("races", "is_public")
