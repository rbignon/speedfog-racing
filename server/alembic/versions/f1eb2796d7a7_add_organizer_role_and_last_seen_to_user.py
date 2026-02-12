"""add organizer role and last_seen to user

Revision ID: f1eb2796d7a7
Revises: 7bce465612ca
Create Date: 2026-02-12 11:23:32.864025

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1eb2796d7a7"
down_revision: str | None = "7bce465612ca"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add 'ORGANIZER' value to the userrole enum (PostgreSQL only).
    # SQLAlchemy's Enum(UserRole) stores enum NAMES (uppercase), not values.
    op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'ORGANIZER' BEFORE 'ADMIN'")

    # Add last_seen column
    op.add_column("users", sa.Column("last_seen", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "last_seen")
    # Note: PostgreSQL does not support removing enum values.
    # The 'organizer' value will remain in the enum after downgrade.
