"""speedrun floor and ranked sessions

Revision ID: e4a1c7d9b3f5
Revises: dd53daaf5e6f
Create Date: 2026-10-29 23:10:00.000000

Pools get an admin-set speedrun floor (pools.speedrun_floor), and solo
sessions gain the columns ranked runs need (debug flags, last IGT change,
admin invalidation).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4a1c7d9b3f5"
down_revision: str | None = "dd53daaf5e6f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("pools", sa.Column("speedrun_floor", sa.Integer(), nullable=True))
    op.add_column(
        "training_sessions", sa.Column("debug_flags", sa.JSON(none_as_null=True), nullable=True)
    )
    op.add_column(
        "training_sessions",
        sa.Column("last_igt_change_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "training_sessions", sa.Column("invalidated_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("training_sessions", sa.Column("invalidated_by_id", sa.Uuid(), nullable=True))
    op.add_column(
        "training_sessions", sa.Column("invalidation_reason", sa.String(500), nullable=True)
    )
    op.create_foreign_key(
        "fk_training_sessions_invalidated_by_id",
        "training_sessions",
        "users",
        ["invalidated_by_id"],
        ["id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "fk_training_sessions_invalidated_by_id", "training_sessions", type_="foreignkey"
    )
    op.drop_column("training_sessions", "invalidation_reason")
    op.drop_column("training_sessions", "invalidated_by_id")
    op.drop_column("training_sessions", "invalidated_at")
    op.drop_column("training_sessions", "last_igt_change_at")
    op.drop_column("training_sessions", "debug_flags")
    op.drop_column("pools", "speedrun_floor")
