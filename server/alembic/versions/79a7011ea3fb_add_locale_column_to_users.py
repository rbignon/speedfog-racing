"""add locale column to users

Revision ID: 79a7011ea3fb
Revises: c4f08502a666
Create Date: 2026-02-19 11:03:32.974770

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "79a7011ea3fb"
down_revision: str | None = "c4f08502a666"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("locale", sa.String(length=10), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "locale")
