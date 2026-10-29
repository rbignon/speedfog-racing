"""speedrun run kinds

Revision ID: c3a9d71e5b24
Revises: 99ed26786aea
Create Date: 2026-10-29 10:00:00.000000

Training sessions record their mode (practice, speedrun, set_seed) and races
whether their seed was chosen. Existing rows become practice sessions and
ordinary races.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3a9d71e5b24"
down_revision: str | None = "99ed26786aea"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

mode_enum = sa.Enum("PRACTICE", "SPEEDRUN", "SET_SEED", name="trainingsessionmode")


def upgrade() -> None:
    mode_enum.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.add_column(sa.Column("mode", mode_enum, server_default="PRACTICE", nullable=False))
    with op.batch_alter_table("races") as batch_op:
        batch_op.add_column(sa.Column("set_seed", sa.Boolean(), server_default="0", nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("races") as batch_op:
        batch_op.drop_column("set_seed")
    with op.batch_alter_table("training_sessions") as batch_op:
        batch_op.drop_column("mode")
    mode_enum.drop(op.get_bind(), checkfirst=True)
