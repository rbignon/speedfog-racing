"""add reported seed status and report fields

Revision ID: 023e377bfdd8
Revises: 9ab1de26267c
Create Date: 2026-04-01 13:47:23.086740

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "023e377bfdd8"
down_revision: str | None = "9ab1de26267c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add REPORTED to seedstatus enum
    op.execute("ALTER TYPE seedstatus ADD VALUE IF NOT EXISTS 'REPORTED'")

    op.add_column("seeds", sa.Column("reported_by_id", sa.UUID(), nullable=True))
    op.add_column("seeds", sa.Column("reported_reason", sa.Text(), nullable=True))
    op.add_column("seeds", sa.Column("reported_at", sa.DateTime(timezone=True), nullable=True))
    op.create_foreign_key("fk_seeds_reported_by_id", "seeds", "users", ["reported_by_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_seeds_reported_by_id", "seeds", type_="foreignkey")
    op.drop_column("seeds", "reported_at")
    op.drop_column("seeds", "reported_reason")
    op.drop_column("seeds", "reported_by_id")
    # Note: cannot remove enum value in PostgreSQL
