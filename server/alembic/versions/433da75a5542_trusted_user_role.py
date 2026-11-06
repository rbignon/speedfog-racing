"""trusted user role

Revision ID: 433da75a5542
Revises: 4c8d1e6f2a37
Create Date: 2026-11-06 10:30:00.000000

Users get a TRUSTED role between ORGANIZER and ADMIN. PostgreSQL stores the
enum names; SQLite stores them as plain strings, so it needs no schema change.
The downgrade turns trusted users back into organizers and rebuilds the
PostgreSQL type without TRUSTED.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "433da75a5542"
down_revision: str | None = "4c8d1e6f2a37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _is_postgresql() -> bool:
    # The migration context, not op.get_bind(): it also answers in offline (--sql) mode.
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    if _is_postgresql():
        # ALTER TYPE ... ADD VALUE cannot run inside a transaction block
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'TRUSTED' BEFORE 'ADMIN'")


def downgrade() -> None:
    op.execute("UPDATE users SET role = 'ORGANIZER' WHERE role = 'TRUSTED'")
    if _is_postgresql():
        # PostgreSQL cannot drop an enum value: rebuild the type without it. The
        # column default refers to the type, so it is dropped and set again.
        op.execute("ALTER TABLE users ALTER COLUMN role DROP DEFAULT")
        op.execute("ALTER TYPE userrole RENAME TO userrole_old")
        op.execute("CREATE TYPE userrole AS ENUM ('USER', 'ORGANIZER', 'ADMIN', 'SYSTEM')")
        op.execute("ALTER TABLE users ALTER COLUMN role TYPE userrole USING role::text::userrole")
        op.execute("ALTER TABLE users ALTER COLUMN role SET DEFAULT 'ORGANIZER'")
        op.execute("DROP TYPE userrole_old")
