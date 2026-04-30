"""add rewards tables and user equip columns

Revision ID: 0fc186a28d5d
Revises: ba25d0d70148
Create Date: 2026-04-30 13:55:20.743174

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0fc186a28d5d"
down_revision: str | None = "ba25d0d70148"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    # Add equip columns to users
    op.add_column("users", sa.Column("equipped_badge_id", sa.String(length=50), nullable=True))
    op.add_column(
        "users", sa.Column("equipped_name_template_id", sa.String(length=50), nullable=True)
    )

    # Create badge_grants table
    op.create_table(
        "badge_grants",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("badge_id", sa.String(length=50), nullable=False),
        sa.Column(
            "granted_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("granted_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reason", sa.String(length=200), nullable=True),
        sa.ForeignKeyConstraint(["granted_by"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_badge_grants_user_id", "badge_grants", ["user_id"], unique=False)
    op.create_index(
        "ix_badge_grants_active",
        "badge_grants",
        ["badge_id", "user_id"],
        unique=False,
        postgresql_where=sa.text("revoked_at IS NULL"),
        sqlite_where=sa.text("revoked_at IS NULL"),
    )

    # Create name_template_unlocks table
    op.create_table(
        "name_template_unlocks",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("template_id", sa.String(length=50), nullable=False),
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
        sa.UniqueConstraint(
            "user_id", "template_id", name="uq_name_template_unlocks_user_template"
        ),
    )
    op.create_index(
        "ix_name_template_unlocks_user_id", "name_template_unlocks", ["user_id"], unique=False
    )

    # Create reward_notifications table
    op.create_table(
        "reward_notifications",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("kind", sa.String(length=40), nullable=False),
        sa.Column("reward_id", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("dismissed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_reward_notifications_user_id", "reward_notifications", ["user_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_reward_notifications_user_id", table_name="reward_notifications")
    op.drop_table("reward_notifications")

    op.drop_index("ix_name_template_unlocks_user_id", table_name="name_template_unlocks")
    op.drop_table("name_template_unlocks")

    op.drop_index("ix_badge_grants_active", table_name="badge_grants")
    op.drop_index("ix_badge_grants_user_id", table_name="badge_grants")
    op.drop_table("badge_grants")

    op.drop_column("users", "equipped_name_template_id")
    op.drop_column("users", "equipped_badge_id")
