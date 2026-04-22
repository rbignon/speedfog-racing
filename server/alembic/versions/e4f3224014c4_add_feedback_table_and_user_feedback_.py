"""add feedback table and user.feedback_prompted_at

Revision ID: e4f3224014c4
Revises: a4e2b1c5d7f3
Create Date: 2026-04-22 18:01:44.786843

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4f3224014c4"
down_revision: str | None = "a4e2b1c5d7f3"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.execute(sa.text("COMMIT"))
    feedback_source_enum = postgresql.ENUM(
        "POST_FIRST_RACE", "USER_MENU", name="feedback_source", create_type=False
    )
    feedback_source_enum.create(op.get_bind(), checkfirst=True)
    op.execute(sa.text("BEGIN"))

    op.create_table(
        "feedback",
        sa.Column("id", sa.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "user_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id"),
            nullable=False,
        ),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("source", feedback_source_enum, nullable=False),
        sa.Column(
            "race_id",
            sa.UUID(as_uuid=True),
            sa.ForeignKey("races.id"),
            nullable=True,
        ),
        sa.Column("races_played_at_feedback", sa.Integer(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.CheckConstraint("rating >= 1 AND rating <= 5", name="ck_feedback_rating_range"),
    )
    op.create_index("ix_feedback_created_at", "feedback", ["created_at"])
    op.create_index("ix_feedback_user_id", "feedback", ["user_id"])

    op.add_column(
        "users",
        sa.Column("feedback_prompted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "feedback_prompted_at")
    op.drop_index("ix_feedback_user_id", table_name="feedback")
    op.drop_index("ix_feedback_created_at", table_name="feedback")
    op.drop_table("feedback")
    op.execute("DROP TYPE IF EXISTS feedback_source")
