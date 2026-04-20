"""add late-join and private_dag to races

Revision ID: db417ce6de90
Revises: 9d6fcec26ada
Create Date: 2026-04-20 19:44:13.900408

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "db417ce6de90"
down_revision: str | None = "9d6fcec26ada"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "races",
        sa.Column("registration_closes_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "races",
        sa.Column("race_ends_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "races",
        sa.Column(
            "private_dag",
            sa.Boolean(),
            nullable=False,
            server_default="0",
        ),
    )


def downgrade() -> None:
    op.drop_column("races", "private_dag")
    op.drop_column("races", "race_ends_at")
    op.drop_column("races", "registration_closes_at")
