"""add event signups

Revision ID: a3e5c7d9b1f2
Revises: 5974b2a0c2a6
Create Date: 2026-09-15 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3e5c7d9b1f2"
down_revision: str | None = "5974b2a0c2a6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "event_signups",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("event_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("event_id", "user_id", name="uq_event_signups_event_user"),
    )
    op.create_index("ix_event_signups_event_id", "event_signups", ["event_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_event_signups_event_id", table_name="event_signups")
    op.drop_table("event_signups")
