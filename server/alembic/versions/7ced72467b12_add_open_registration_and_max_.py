"""add open_registration and max_participants to race

Revision ID: 7ced72467b12
Revises: 525e2a1a06b2
Create Date: 2026-02-20 09:56:14.018030

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7ced72467b12"
down_revision: str | None = "525e2a1a06b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "races", sa.Column("open_registration", sa.Boolean(), server_default="0", nullable=False)
    )
    op.add_column("races", sa.Column("max_participants", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "max_participants")
    op.drop_column("races", "open_registration")
