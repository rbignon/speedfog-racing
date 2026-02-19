"""add current_zone to training_sessions

Revision ID: 3a3d9111c571
Revises: 79a7011ea3fb
Create Date: 2026-02-19 17:47:25.161123

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3a3d9111c571"
down_revision: str | None = "79a7011ea3fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "training_sessions", sa.Column("current_zone", sa.String(length=100), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("training_sessions", "current_zone")
