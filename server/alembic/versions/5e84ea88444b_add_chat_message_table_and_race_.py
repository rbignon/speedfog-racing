"""add chat_message table and race finished_at

Revision ID: 5e84ea88444b
Revises: 023e377bfdd8
Create Date: 2026-04-03 16:29:25.325020

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e84ea88444b"
down_revision: str | None = "023e377bfdd8"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    chatchannel_enum = sa.Enum("participants", "public", name="chatchannel")
    chatchannel_enum.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "chat_messages",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "race_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("races.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("channel", chatchannel_enum, nullable=False),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("message", sa.String(500), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
    )
    op.create_index(
        "ix_chat_messages_race_channel_created",
        "chat_messages",
        ["race_id", "channel", "created_at"],
    )
    op.add_column("races", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "finished_at")
    op.drop_index("ix_chat_messages_race_channel_created", table_name="chat_messages")
    op.drop_table("chat_messages")
    op.execute("DROP TYPE IF EXISTS chatchannel")
