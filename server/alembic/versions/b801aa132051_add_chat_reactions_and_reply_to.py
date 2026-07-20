"""add chat reactions and reply_to

Revision ID: b801aa132051
Revises: 8a558a690dae
Create Date: 2026-07-20 16:31:32.357162

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b801aa132051"
down_revision: str | None = "8a558a690dae"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "chat_message_reactions",
        sa.Column("message_id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("emoji", sa.String(length=16), nullable=False),
        sa.ForeignKeyConstraint(["message_id"], ["chat_messages.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("message_id", "user_id", "emoji"),
    )
    op.add_column("chat_messages", sa.Column("reply_to_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        op.f("fk_chat_messages_reply_to_id_chat_messages"),
        "chat_messages",
        "chat_messages",
        ["reply_to_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_chat_messages_reply_to_id_chat_messages"), "chat_messages", type_="foreignkey"
    )
    op.drop_column("chat_messages", "reply_to_id")
    op.drop_table("chat_message_reactions")
