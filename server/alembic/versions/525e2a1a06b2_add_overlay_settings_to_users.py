"""add overlay_settings to users

Revision ID: 525e2a1a06b2
Revises: 736fc1ba38f3
Create Date: 2026-02-20 09:31:58.956343

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "525e2a1a06b2"
down_revision: str | None = "736fc1ba38f3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("overlay_settings", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "overlay_settings")
