"""add composite indexes for scale

Revision ID: 163dac67f6db
Revises: ba6e06eaf96a
Create Date: 2026-04-05 12:11:56.548922

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "163dac67f6db"
down_revision: str | None = "ba6e06eaf96a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Speeds up per-user trait recomputation and abandon checks.
    op.create_index(
        "ix_participants_user_race_status",
        "participants",
        ["user_id", "race_id", "status"],
    )
    # Speeds up leaderboard lookups and Race.participants selectinload cascades.
    op.create_index(
        "ix_participants_race_user",
        "participants",
        ["race_id", "user_id"],
    )
    # Speeds up the organizer dashboard (races listed by organizer).
    op.create_index(
        "ix_races_organizer",
        "races",
        ["organizer_id"],
    )
    # Speeds up user profile page (sessions filtered by status).
    op.create_index(
        "ix_training_sessions_user_status",
        "training_sessions",
        ["user_id", "status"],
    )


def downgrade() -> None:
    op.drop_index("ix_training_sessions_user_status", table_name="training_sessions")
    op.drop_index("ix_races_organizer", table_name="races")
    op.drop_index("ix_participants_race_user", table_name="participants")
    op.drop_index("ix_participants_user_race_status", table_name="participants")
