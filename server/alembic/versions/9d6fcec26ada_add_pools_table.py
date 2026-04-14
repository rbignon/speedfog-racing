"""add pools table

Revision ID: 9d6fcec26ada
Revises: efa89720af9a
Create Date: 2026-04-14 10:20:32.468132

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d6fcec26ada"
down_revision: str | None = "efa89720af9a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "pools",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column(
            "enabled",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column("config", sa.JSON(), nullable=False),
        sa.Column("last_scanned_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("name"),
    )

    # Backfill pools from existing distinct seed pool names. `config` is left
    # as an empty JSON object; the operator is expected to run
    # `speedfog-scan-seeds` right after the migration to populate it.
    op.execute(
        sa.text(
            """
            INSERT INTO pools (id, name, enabled, config, created_at)
            SELECT gen_random_uuid(), pool_name, true, '{}'::json, now()
            FROM (SELECT DISTINCT pool_name FROM seeds) AS p
            """
        )
    )

    op.create_foreign_key(
        "fk_seeds_pool_name",
        "seeds",
        "pools",
        ["pool_name"],
        ["name"],
    )


def downgrade() -> None:
    op.drop_constraint("fk_seeds_pool_name", "seeds", type_="foreignkey")
    op.drop_table("pools")
