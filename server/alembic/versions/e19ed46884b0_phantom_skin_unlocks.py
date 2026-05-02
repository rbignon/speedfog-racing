"""phantom_skin_unlocks

Revision ID: e19ed46884b0
Revises: 0fc186a28d5d
Create Date: 2026-05-02 12:01:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e19ed46884b0"
down_revision: str | None = "0fc186a28d5d"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "phantom_skin_unlocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("skin_id", sa.String(length=50), nullable=False),
        sa.Column(
            "unlocked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "skin_id", name="uq_phantom_skin_unlocks_user_skin"),
    )
    op.create_index(
        "ix_phantom_skin_unlocks_user_id", "phantom_skin_unlocks", ["user_id"], unique=False
    )

    op.add_column(
        "users", sa.Column("equipped_phantom_skin_id", sa.String(length=50), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "equipped_phantom_skin_id")

    op.drop_index("ix_phantom_skin_unlocks_user_id", table_name="phantom_skin_unlocks")
    op.drop_table("phantom_skin_unlocks")
