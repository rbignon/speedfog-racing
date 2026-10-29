"""speedrun run kinds

Revision ID: c3a9d71e5b24
Revises: 99ed26786aea
Create Date: 2026-10-29 10:00:00.000000

Races and training sessions record one immutable mode (normal, speedrun,
set_seed). Existing rows become normal, except the finished community races
(a seed, no daily, no event, counted in stats), which become speedrun races so
the boards keep the runs they counted before modes existed.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9d71e5b24"
down_revision: str | None = "99ed26786aea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

mode_enum = sa.Enum("NORMAL", "SPEEDRUN", "SET_SEED", name="runmode")


def upgrade() -> None:
    mode_enum.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.add_column(sa.Column("mode", mode_enum, server_default="NORMAL", nullable=False))
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(sa.Column("mode", mode_enum, server_default="NORMAL", nullable=False))
    op.execute(
        sa.text(
            "UPDATE races SET mode = 'SPEEDRUN' WHERE status = 'FINISHED' "
            "AND seed_id IS NOT NULL AND daily_date IS NULL AND event_id IS NULL "
            "AND exclude_from_stats = false"
        )
    )


def downgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("mode")
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.drop_column("mode")
    mode_enum.drop(op.get_bind(), checkfirst=True)
