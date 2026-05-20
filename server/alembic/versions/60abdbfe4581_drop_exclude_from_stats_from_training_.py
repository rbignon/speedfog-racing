"""drop exclude_from_stats from training_sessions

Revision ID: 60abdbfe4581
Revises: fffc83b0f2c4
Create Date: 2026-05-20 09:10:51.050470

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "60abdbfe4581"
down_revision: str | None = "fffc83b0f2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("training_sessions", "exclude_from_stats")


def downgrade() -> None:
    op.add_column(
        "training_sessions",
        sa.Column(
            "exclude_from_stats", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
    )
