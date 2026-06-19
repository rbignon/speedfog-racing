"""add race custom_rules

Revision ID: ac2b8c72817b
Revises: 60abdbfe4581
Create Date: 2026-06-19 18:53:09.898909

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ac2b8c72817b"
down_revision: str | None = "60abdbfe4581"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("races", sa.Column("custom_rules", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "custom_rules")
