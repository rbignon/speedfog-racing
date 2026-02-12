"""drop has_seed_pack and update seed folder_path to zip

Revision ID: 72251e529594
Revises: f1eb2796d7a7
Create Date: 2026-02-12 13:48:38.723391

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "72251e529594"
down_revision: str | None = "f1eb2796d7a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("participants", "has_seed_pack")
    op.execute("UPDATE seeds SET folder_path = folder_path || '.zip'")


def downgrade() -> None:
    op.add_column(
        "participants",
        sa.Column("has_seed_pack", sa.Boolean(), server_default="0", nullable=False),
    )
    # Strip .zip suffix from folder_path
    op.execute(
        "UPDATE seeds SET folder_path = SUBSTR(folder_path, 1, LENGTH(folder_path) - 4) "
        "WHERE folder_path LIKE '%.zip'"
    )
