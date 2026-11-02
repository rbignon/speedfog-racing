"""race rerolled without report

Revision ID: b7e3c2a91f04
Revises: 9a564dc19e71
Create Date: 2026-11-02 15:30:00.000000

Races get rerolled_without_report: set by a reroll without a seed report that
gives up a seed the race could have counted on. Such a community race counts
on no speedrun board. False for every existing race: no backfill, a race
rerolled before this release keeps counting (as one reset before it does).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7e3c2a91f04"
down_revision: str | None = "9a564dc19e71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(
            sa.Column("rerolled_without_report", sa.Boolean(), server_default="0", nullable=False)
        )


def downgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("rerolled_without_report")
