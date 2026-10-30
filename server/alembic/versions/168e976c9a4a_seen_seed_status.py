"""seen seed status

Revision ID: 168e976c9a4a
Revises: e4a1c7d9b3f5
Create Date: 2026-10-30 10:30:00.000000

Seeds get a SEEN status: drawn for a race that never started (rerolled or
deleted in SETUP, or a restored report), so only normal races draw them again.
PostgreSQL stores the enum names; SQLite stores them as plain strings, so it
needs no schema change. The downgrade turns SEEN seeds into CONSUMED ones (out
of every draw) and rebuilds the PostgreSQL type without SEEN.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "168e976c9a4a"
down_revision: str | None = "e4a1c7d9b3f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgresql() -> bool:
    # The migration context, not op.get_bind(): it also answers in offline (--sql) mode.
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgresql():
        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE seedstatus ADD VALUE IF NOT EXISTS 'SEEN'")


def downgrade() -> None:
    op.execute("UPDATE seeds SET status = 'CONSUMED' WHERE status = 'SEEN'")
    if _is_postgresql():
        # PostgreSQL cannot drop an enum value: rebuild the type without it. The
        # column default refers to the type, so it is dropped and set again.
        op.execute("ALTER TABLE seeds ALTER COLUMN status DROP DEFAULT")
        op.execute("ALTER TYPE seedstatus RENAME TO seedstatus_old")
        op.execute(
            "CREATE TYPE seedstatus AS ENUM ('AVAILABLE', 'CONSUMED', 'DISCARDED', 'REPORTED')"
        )
        op.execute(
            "ALTER TABLE seeds ALTER COLUMN status TYPE seedstatus USING status::text::seedstatus"
        )
        op.execute("ALTER TABLE seeds ALTER COLUMN status SET DEFAULT 'AVAILABLE'")
        op.execute("DROP TYPE seedstatus_old")
