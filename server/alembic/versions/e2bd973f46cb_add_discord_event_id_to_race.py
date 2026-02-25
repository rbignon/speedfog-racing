"""add discord_event_id to race

Revision ID: e2bd973f46cb
Revises: 1aaa8287c0fc
Create Date: 2026-02-25 13:32:23.489309

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2bd973f46cb"
down_revision: str | None = "1aaa8287c0fc"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("races", sa.Column("discord_event_id", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("races", "discord_event_id")
