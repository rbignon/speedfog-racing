"""add user ban columns

Revision ID: c9e5a1b3f4d6
Revises: b8d4f0a2e3c5
Create Date: 2026-10-01 22:00:02.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e5a1b3f4d6"
down_revision: str | None = "b8d4f0a2e3c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("users", sa.Column("banned_by_id", sa.UUID(), nullable=True))
    op.create_foreign_key("fk_users_banned_by_id", "users", "users", ["banned_by_id"], ["id"])
    op.add_column("users", sa.Column("ban_reason", sa.String(500), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "ban_reason")
    op.drop_constraint("fk_users_banned_by_id", "users", type_="foreignkey")
    op.drop_column("users", "banned_by_id")
    op.drop_column("users", "banned_at")
