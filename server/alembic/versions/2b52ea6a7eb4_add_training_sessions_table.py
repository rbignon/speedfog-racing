"""add training_sessions table

Revision ID: 2b52ea6a7eb4
Revises: 72251e529594
Create Date: 2026-02-14 13:24:01.987544

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "2b52ea6a7eb4"
down_revision: str | None = "72251e529594"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP TYPE IF EXISTS trainingsessionstatus")
    op.execute("CREATE TYPE trainingsessionstatus AS ENUM ('ACTIVE', 'FINISHED', 'ABANDONED')")
    op.execute("""
        CREATE TABLE training_sessions (
            id UUID PRIMARY KEY,
            user_id UUID NOT NULL REFERENCES users(id),
            seed_id UUID NOT NULL REFERENCES seeds(id),
            mod_token VARCHAR(100) NOT NULL UNIQUE,
            status trainingsessionstatus DEFAULT 'ACTIVE',
            igt_ms INTEGER DEFAULT 0,
            death_count INTEGER DEFAULT 0,
            progress_nodes JSONB,
            created_at TIMESTAMPTZ DEFAULT now(),
            finished_at TIMESTAMPTZ
        )
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS training_sessions")
    op.execute("DROP TYPE IF EXISTS trainingsessionstatus")
