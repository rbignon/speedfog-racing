"""add dominant_description to player_trait_scores

Revision ID: 6a8f4c47afc4
Revises: 6f150ab7d804
Create Date: 2026-03-27 13:52:05.477587

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "6a8f4c47afc4"
down_revision: str | None = "6f150ab7d804"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "player_trait_scores", sa.Column("dominant_description", sa.String(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("player_trait_scores", "dominant_description")
