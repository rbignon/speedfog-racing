"""add has_seed_pack to participant

Revision ID: 052c6d411564
Revises: 882a8df28326
Create Date: 2026-02-08 17:07:17.393480

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "052c6d411564"
down_revision: str | None = "882a8df28326"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "participants", sa.Column("has_seed_pack", sa.Boolean(), server_default="0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("participants", "has_seed_pack")
