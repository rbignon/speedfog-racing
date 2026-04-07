"""make chat_message user_id nullable for system messages

Revision ID: efa89720af9a
Revises: c7a735cadb16
Create Date: 2026-04-07 20:27:57.538228

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "efa89720af9a"
down_revision: str | None = "c7a735cadb16"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column("chat_messages", "user_id", existing_type=sa.UUID(), nullable=True)


def downgrade() -> None:
    op.alter_column("chat_messages", "user_id", existing_type=sa.UUID(), nullable=False)
