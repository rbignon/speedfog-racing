"""add created_at to participants

Revision ID: 3f7a2c1d8e9b
Revises: e4f3224014c4
Create Date: 2026-04-26 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3f7a2c1d8e9b"
down_revision: str | None = "e4f3224014c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "participants",
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("participants", "created_at")
