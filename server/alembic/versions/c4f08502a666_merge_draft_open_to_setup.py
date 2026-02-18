"""merge draft open to setup

Revision ID: c4f08502a666
Revises: a2dc7553c456
Create Date: 2026-02-18 13:08:15.580621

"""

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4f08502a666"
down_revision: str = "a2dc7553c456"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        # Add new SETUP value to the PostgreSQL enum type.
        # Note: Alembic/PG cannot easily remove enum values, so DRAFT and OPEN
        # will linger in the type definition but never be used by application code.
        op.execute("ALTER TYPE racestatus ADD VALUE IF NOT EXISTS 'SETUP'")
        op.execute("COMMIT")  # PG requires commit after ADD VALUE before using it
        op.execute("UPDATE races SET status = 'SETUP' WHERE status IN ('DRAFT', 'OPEN')")
    else:
        # SQLite: enums stored as plain strings
        op.execute("UPDATE races SET status = 'setup' WHERE status IN ('draft', 'open')")


def downgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name

    if dialect == "postgresql":
        op.execute("UPDATE races SET status = 'DRAFT' WHERE status = 'SETUP'")
    else:
        op.execute("UPDATE races SET status = 'draft' WHERE status = 'setup'")
