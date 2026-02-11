"""change seed_number from integer to string for uuid slugs

Revision ID: 7bce465612ca
Revises: e9099620f295
Create Date: 2026-02-11 20:42:28.794427

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7bce465612ca"
down_revision: str | None = "e9099620f295"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Seed directories now use UUID slugs instead of incremental numbers.
    # Existing integer values are cast to strings (e.g. 123456 -> "123456").
    op.alter_column(
        "seeds",
        "seed_number",
        existing_type=sa.INTEGER(),
        type_=sa.String(length=50),
        existing_nullable=False,
        postgresql_using="seed_number::text",
    )


def downgrade() -> None:
    # NOTE: This will fail if any seed_number contains non-numeric slugs (e.g. "a1b2c3d4").
    # Downgrade requires manual cleanup of UUID-style slugs first.
    op.alter_column(
        "seeds",
        "seed_number",
        existing_type=sa.String(length=50),
        type_=sa.INTEGER(),
        existing_nullable=False,
        postgresql_using="seed_number::integer",
    )
