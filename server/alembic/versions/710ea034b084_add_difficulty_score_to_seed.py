"""add difficulty_score to seed

Revision ID: 710ea034b084
Revises: 6a8f4c47afc4
Create Date: 2026-03-27 17:11:11.165981

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "710ea034b084"
down_revision: str | None = "6a8f4c47afc4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "seeds", sa.Column("difficulty_score", sa.Float(), server_default="0.0", nullable=False)
    )


def downgrade() -> None:
    op.drop_column("seeds", "difficulty_score")
