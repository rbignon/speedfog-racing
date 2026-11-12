"""add race_items to races

Revision ID: c4a91e7d52b8
Revises: 50546370bf40
Create Date: 2026-11-12 15:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4a91e7d52b8"
down_revision: str | None = "50546370bf40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "races",
        sa.Column("race_items", sa.Boolean(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("races", "race_items")
