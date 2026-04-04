"""add timezone to users

Revision ID: ba6e06eaf96a
Revises: 5e84ea88444b
Create Date: 2026-04-04 22:27:27.615821

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ba6e06eaf96a"
down_revision: str | None = "5e84ea88444b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("timezone", sa.String(length=50), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "timezone")
