"""add layer_entry_igts to participants

Revision ID: c7a735cadb16
Revises: 7ec969392629
Create Date: 2026-04-05 23:21:39.077485

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a735cadb16"
down_revision: str | None = "7ec969392629"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Empty default: existing rows are not backfilled. sort_leaderboard
    # falls back to the legacy get_layer_entry_igt scan when the cache is
    # empty, so historical races keep rendering correctly; newly visited
    # layers populate the cache going forward.
    op.add_column(
        "participants",
        sa.Column(
            "layer_entry_igts",
            sa.JSON(),
            nullable=False,
            server_default="{}",
        ),
    )


def downgrade() -> None:
    op.drop_column("participants", "layer_entry_igts")
