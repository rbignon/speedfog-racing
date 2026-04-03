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
    # Create ChatChannel enum type if it does not already exist
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_type WHERE typname = 'chatchannel') THEN
                CREATE TYPE chatchannel AS ENUM ('participants', 'public');
            END IF;
        END
        $$
    """)

    # Create chat_messages table
    op.execute("""
        CREATE TABLE IF NOT EXISTS chat_messages (
            id UUID NOT NULL,
            race_id UUID NOT NULL REFERENCES races(id) ON DELETE CASCADE,
            channel chatchannel NOT NULL,
            user_id UUID NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            message VARCHAR(500) NOT NULL,
            created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
            PRIMARY KEY (id)
        )
    """)

    # Create composite index for efficient channel history queries
    op.execute("""
        CREATE INDEX IF NOT EXISTS ix_chat_messages_race_channel_created
        ON chat_messages (race_id, channel, created_at)
    """)

    # Add finished_at to races
    op.add_column("races", sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "finished_at")
    op.drop_table("chat_messages")
    op.execute("DROP TYPE IF EXISTS chatchannel")
