"""default new users to organizer role

Revision ID: 9ab1de26267c
Revises: 710ea034b084
Create Date: 2026-03-29 18:22:10.461813

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9ab1de26267c"
down_revision: str | None = "710ea034b084"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Change column default for new users
    op.alter_column(
        "users",
        "role",
        server_default="ORGANIZER",
    )
    # Promote existing users with USER role to ORGANIZER
    op.execute("UPDATE users SET role = 'ORGANIZER' WHERE role = 'USER'")


def downgrade() -> None:
    op.alter_column(
        "users",
        "role",
        server_default="USER",
    )
    # Note: cannot reliably revert individual user roles
