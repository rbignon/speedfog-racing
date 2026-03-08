"""rename progress_nodes to zone_history

Revision ID: a1b2c3d4e5f6
Revises: 079038f204fb
Create Date: 2026-03-08 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "079038f204fb"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "training_sessions",
        "progress_nodes",
        new_column_name="zone_history",
    )


def downgrade() -> None:
    op.alter_column(
        "training_sessions",
        "zone_history",
        new_column_name="progress_nodes",
    )
