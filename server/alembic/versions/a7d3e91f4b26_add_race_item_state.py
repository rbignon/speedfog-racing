"""add held items and the race item log

Revision ID: a7d3e91f4b26
Revises: c4a91e7d52b8
Create Date: 2026-11-12 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d3e91f4b26"
down_revision: str | None = "c4a91e7d52b8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("participants", sa.Column("held_item", sa.JSON(), nullable=True))
    op.add_column(
        "participants",
        sa.Column("item_grant_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_table(
        "race_item_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column(
            "race_id",
            sa.Uuid(),
            sa.ForeignKey("races.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "participant_id",
            sa.Uuid(),
            sa.ForeignKey("participants.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("item", sa.String(50), nullable=False),
        sa.Column("igt_ms", sa.Integer(), nullable=True),
        sa.Column("targets", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index(
        "ix_race_item_events_race_created", "race_item_events", ["race_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_race_item_events_race_created", table_name="race_item_events")
    op.drop_table("race_item_events")
    op.drop_column("participants", "item_grant_count")
    op.drop_column("participants", "held_item")
