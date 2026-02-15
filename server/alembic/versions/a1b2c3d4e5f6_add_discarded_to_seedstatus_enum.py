"""add DISCARDED to seedstatus enum

Revision ID: a1b2c3d4e5f6
Revises: 2b52ea6a7eb4
Create Date: 2026-02-15 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "2b52ea6a7eb4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ALTER TYPE ... ADD VALUE cannot run inside a transaction block
    with op.get_context().autocommit_block():
        op.execute("ALTER TYPE seedstatus ADD VALUE IF NOT EXISTS 'DISCARDED'")


def downgrade() -> None:
    # PostgreSQL does not support removing enum values.
    # The extra value is harmless if unused.
    pass
