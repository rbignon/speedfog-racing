"""add disqualified participant status

Revision ID: a7c3e9f1d2b4
Revises: e8b3d5f1a7c2
Create Date: 2026-10-01 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3e9f1d2b4"
down_revision: str | None = "e8b3d5f1a7c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block in PostgreSQL.
    # Commit the current transaction, add the enum value, then re-open for the rest.
    op.execute(sa.text("COMMIT"))
    op.execute(sa.text("ALTER TYPE participantstatus ADD VALUE IF NOT EXISTS 'DISQUALIFIED'"))
    op.execute(sa.text("BEGIN"))


def downgrade() -> None:
    # Note: cannot remove enum value in PostgreSQL
    pass
