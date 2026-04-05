"""add indexes for inactivity monitor, stats, and seed selection

Revision ID: 7ec969392629
Revises: 163dac67f6db
Create Date: 2026-04-05 19:46:48.785532

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7ec969392629"
down_revision: str | None = "163dac67f6db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Inactivity monitor: scans every 60s filtering status + last_igt_change_at.
    op.create_index(
        "ix_participants_status_igt_change",
        "participants",
        ["status", "last_igt_change_at"],
    )
    # Running-race lookups (WebSocket handlers, inactivity monitor, admin panel).
    op.create_index("ix_races_status", "races", ["status"])
    # Date-range filters in analytics and stats endpoints.
    op.create_index("ix_races_started_at", "races", ["started_at"])
    # Seed selection: filters on (pool_name, status) in seed_service.
    op.create_index("ix_seeds_pool_status", "seeds", ["pool_name", "status"])
    # User-scoped chat access (moderation, cascade on user deletion).
    op.create_index("ix_chat_messages_user", "chat_messages", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_chat_messages_user", table_name="chat_messages")
    op.drop_index("ix_seeds_pool_status", table_name="seeds")
    op.drop_index("ix_races_started_at", table_name="races")
    op.drop_index("ix_races_status", table_name="races")
    op.drop_index("ix_participants_status_igt_change", table_name="participants")
