"""race seed was seen

Revision ID: e178d7c8066b
Revises: 168e976c9a4a
Create Date: 2026-10-30 15:52:54.845592

Races get seed_was_seen: set when a draw takes a SEEN seed, cleared when one
takes an AVAILABLE seed. A race on a SEEN seed counts on no speedrun board,
even once attached to an event. No backfill: SEEN seeds arrive with the
previous revision, in the same release, so no released race drew one.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e178d7c8066b"
down_revision: str | None = "168e976c9a4a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(
            sa.Column("seed_was_seen", sa.Boolean(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("seed_was_seen")
