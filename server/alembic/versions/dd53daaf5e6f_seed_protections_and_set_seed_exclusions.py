"""seed protections and set seed exclusions

Revision ID: dd53daaf5e6f
Revises: c3a9d71e5b24
Create Date: 2026-10-29 21:13:15.994510

Players protect played seeds from the purge (seed_protections), and an admin
can exclude a seed from Set Seed (seeds.set_seed_excluded_*).
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "dd53daaf5e6f"
down_revision: str | None = "c3a9d71e5b24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "seed_protections",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("seed_id", sa.Uuid(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["seed_id"], ["seeds.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "seed_id", name="uq_seed_protections_user_seed"),
    )
    op.create_index("ix_seed_protections_seed", "seed_protections", ["seed_id"], unique=False)
    op.add_column(
        "seeds", sa.Column("set_seed_excluded_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("seeds", sa.Column("set_seed_excluded_reason", sa.String(500), nullable=True))
    op.add_column("seeds", sa.Column("set_seed_excluded_by_id", sa.Uuid(), nullable=True))
    op.create_foreign_key(
        "fk_seeds_set_seed_excluded_by_id", "seeds", "users", ["set_seed_excluded_by_id"], ["id"]
    )


def downgrade() -> None:
    op.drop_constraint("fk_seeds_set_seed_excluded_by_id", "seeds", type_="foreignkey")
    op.drop_column("seeds", "set_seed_excluded_by_id")
    op.drop_column("seeds", "set_seed_excluded_reason")
    op.drop_column("seeds", "set_seed_excluded_at")
    op.drop_index("ix_seed_protections_seed", table_name="seed_protections")
    op.drop_table("seed_protections")
