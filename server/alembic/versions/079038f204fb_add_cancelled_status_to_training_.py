"""add cancelled status to training sessions

Revision ID: 079038f204fb
Revises: afe8e80417ef
Create Date: 2026-03-03 11:41:45.897756

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "079038f204fb"
down_revision: str | None = "afe8e80417ef"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ADD VALUE must be committed before it can be used in DML
    op.execute("COMMIT")
    op.execute("ALTER TYPE trainingsessionstatus ADD VALUE IF NOT EXISTS 'CANCELLED'")
    op.execute("BEGIN")
    # Migrate existing abandoned sessions that never started (no progress)
    op.execute("""
        UPDATE training_sessions
        SET status = 'CANCELLED'
        WHERE status = 'ABANDONED'
          AND (progress_nodes IS NULL OR progress_nodes = '[]'::jsonb)
    """)


def downgrade() -> None:
    # Convert CANCELLED back to ABANDONED (enum value removal not supported in PG)
    op.execute("""
        UPDATE training_sessions
        SET status = 'ABANDONED'
        WHERE status = 'CANCELLED'
    """)
