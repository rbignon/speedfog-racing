"""drop race exclude_from_stats

Revision ID: 4c8d1e6f2a37
Revises: b7e3c2a91f04
Create Date: 2026-11-02 17:30:00.000000

Races lose exclude_from_stats, a leftover of the ELO rating (exclude_from_elo):
the statistics follow the race's mode (``counts_for_community_stats``) and the
Speedrun boards their own rules, so its last reader was the trait rebuild,
which skipped players seen only in Daily Seeds and qualifiers although the
race-end updates scored them. The downgrade brings it back with the values
the code wrote: Daily Seeds, races attached to a qualifier slot, and
speedrun and Set Seed races.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4c8d1e6f2a37"
down_revision: str | None = "b7e3c2a91f04"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("exclude_from_stats")


def downgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(
            sa.Column("exclude_from_stats", sa.Boolean(), server_default="0", nullable=False)
        )
    op.execute(
        "UPDATE races SET exclude_from_stats = true"
        " WHERE daily_date IS NOT NULL OR mode <> 'NORMAL' OR event_slot LIKE 'qualifier:%'"
    )
