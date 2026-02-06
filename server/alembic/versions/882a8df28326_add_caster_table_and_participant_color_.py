"""add caster table and participant color_index zone_history

Revision ID: 882a8df28326
Revises: f14cb23163f8
Create Date: 2026-02-06 17:27:36.983131

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "882a8df28326"
down_revision: str | None = "f14cb23163f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "casters",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("race_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.ForeignKeyConstraint(["race_id"], ["races.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("race_id", "user_id", name="uq_casters_race_user"),
    )
    op.add_column(
        "participants",
        sa.Column("color_index", sa.Integer(), server_default="0", nullable=False),
    )
    op.add_column(
        "participants",
        sa.Column("zone_history", postgresql.JSON(astext_type=sa.Text()), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("participants", "zone_history")
    op.drop_column("participants", "color_index")
    op.drop_table("casters")
