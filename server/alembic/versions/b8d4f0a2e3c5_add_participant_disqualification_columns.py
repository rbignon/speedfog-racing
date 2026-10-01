"""add participant disqualification columns

Revision ID: b8d4f0a2e3c5
Revises: a7c3e9f1d2b4
Create Date: 2026-10-01 22:00:01.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d4f0a2e3c5"
down_revision: str | None = "a7c3e9f1d2b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "participants", sa.Column("disqualified_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("participants", sa.Column("disqualified_by_id", sa.UUID(), nullable=True))
    op.create_foreign_key(
        "fk_participants_disqualified_by_id",
        "participants",
        "users",
        ["disqualified_by_id"],
        ["id"],
    )
    op.add_column(
        "participants", sa.Column("disqualification_reason", sa.String(500), nullable=True)
    )
    op.add_column(
        "participants",
        sa.Column(
            "status_before_disqualification",
            postgresql.ENUM(name="participantstatus", create_type=False),
            nullable=True,
        ),
    )


def downgrade() -> None:
    op.drop_column("participants", "status_before_disqualification")
    op.drop_column("participants", "disqualification_reason")
    op.drop_constraint("fk_participants_disqualified_by_id", "participants", type_="foreignkey")
    op.drop_column("participants", "disqualified_by_id")
    op.drop_column("participants", "disqualified_at")
