"""race rerolled seed ids

Revision ID: 9a564dc19e71
Revises: e178d7c8066b
Create Date: 2026-10-30 18:54:56.221421

Races get rerolled_seed_ids: the seeds their rerolls gave up, which their
later rerolls never draw back. NULL for every existing race, as for a race
never rerolled: no backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9a564dc19e71"
down_revision: str | None = "e178d7c8066b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(sa.Column("rerolled_seed_ids", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("rerolled_seed_ids")
