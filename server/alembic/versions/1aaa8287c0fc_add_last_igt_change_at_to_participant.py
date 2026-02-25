"""add last_igt_change_at to participant

Revision ID: 1aaa8287c0fc
Revises: 7ced72467b12
Create Date: 2026-02-25 10:24:57.519298

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1aaa8287c0fc"
down_revision: str | None = "7ced72467b12"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "participants", sa.Column("last_igt_change_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("participants", "last_igt_change_at")
