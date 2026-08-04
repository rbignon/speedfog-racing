"""add deathless to races

Revision ID: b8ecd1b57d3f
Revises: b801aa132051
Create Date: 2026-08-04 20:45:43.889338

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8ecd1b57d3f"
down_revision: str | None = "b801aa132051"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "races",
        sa.Column("deathless", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("races", "deathless")
