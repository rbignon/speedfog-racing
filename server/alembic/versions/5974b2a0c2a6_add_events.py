"""add events

Revision ID: 5974b2a0c2a6
Revises: 42520d221730
Create Date: 2026-09-09 11:31:53.330130

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5974b2a0c2a6"
down_revision: str | None = "42520d221730"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "events",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("slug", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("partner_name", sa.String(length=100), nullable=True),
        sa.Column("partner_url", sa.String(length=500), nullable=True),
        sa.Column("partner_logo_url", sa.String(length=500), nullable=True),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("qualifier_ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("newcomer_threshold", sa.Integer(), server_default="5", nullable=False),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_events_slug"), "events", ["slug"], unique=True)
    op.add_column("races", sa.Column("event_id", sa.UUID(), nullable=True))
    op.add_column("races", sa.Column("event_slot", sa.String(length=50), nullable=True))
    op.create_index("ix_races_event_id", "races", ["event_id"], unique=False)
    op.create_unique_constraint("uq_races_event_slot", "races", ["event_id", "event_slot"])
    op.create_foreign_key("fk_races_event_id", "races", "events", ["event_id"], ["id"])


def downgrade() -> None:
    op.drop_constraint("fk_races_event_id", "races", type_="foreignkey")
    op.drop_constraint("uq_races_event_slot", "races", type_="unique")
    op.drop_index("ix_races_event_id", table_name="races")
    op.drop_column("races", "event_slot")
    op.drop_column("races", "event_id")
    op.drop_index(op.f("ix_events_slug"), table_name="events")
    op.drop_table("events")
