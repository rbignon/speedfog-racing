"""add the relay token to participants

Revision ID: fc65bff7c839
Revises: a004a9973fb3
Create Date: 2026-11-24 00:31:53.629915

Participants get relay_token, the token drawn when a relay member's save
passes the fresh-save gate (null before), and relay_bound, whether the
member's mod confirmed it wrote that token into the save (false by default).
Existing rows need no backfill: a member validated before this revision gets
no token, and reads as an unbound one.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "fc65bff7c839"
down_revision: str | None = "a004a9973fb3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("participants") as batch_op:
        batch_op.add_column(sa.Column("relay_token", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("relay_bound", sa.Boolean(), nullable=False, server_default="0")
        )


def downgrade() -> None:
    with op.batch_alter_table("participants") as batch_op:
        batch_op.drop_column("relay_bound")
        batch_op.drop_column("relay_token")
