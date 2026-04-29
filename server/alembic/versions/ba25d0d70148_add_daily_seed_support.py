"""add daily seed support

Revision ID: ba25d0d70148
Revises: 3f7a2c1d8e9b
Create Date: 2026-04-29 10:30:49.957904

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "ba25d0d70148"
down_revision: str | None = "3f7a2c1d8e9b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    is_postgres = bind.dialect.name == "postgresql"

    if is_postgres:
        # ALTER TYPE ... ADD VALUE has to run outside any transaction.
        with op.get_context().autocommit_block():
            op.execute(sa.text("ALTER TYPE userrole ADD VALUE IF NOT EXISTS 'SYSTEM'"))

    op.add_column("races", sa.Column("daily_date", sa.Date(), nullable=True))
    op.add_column(
        "races",
        sa.Column(
            "exclude_from_elo",
            sa.Boolean(),
            server_default="0",
            nullable=False,
        ),
    )
    op.create_index(
        "uq_races_daily_date",
        "races",
        ["daily_date"],
        unique=True,
        postgresql_where=sa.text("daily_date IS NOT NULL"),
        sqlite_where=sa.text("daily_date IS NOT NULL"),
    )
    op.create_index("ix_races_daily_date", "races", ["daily_date"])

    op.alter_column(
        "users",
        "api_token",
        existing_type=sa.String(length=100),
        nullable=True,
    )

    op.create_table(
        "daily_seed_schedule",
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("pool_name", sa.String(length=50), nullable=False),
        sa.ForeignKeyConstraint(["pool_name"], ["pools.name"]),
        sa.PrimaryKeyConstraint("weekday"),
    )

    op.bulk_insert(
        sa.table(
            "daily_seed_schedule",
            sa.column("weekday", sa.Integer),
            sa.column("pool_name", sa.String),
        ),
        [{"weekday": weekday, "pool_name": "standard"} for weekday in range(7)],
    )

    if is_postgres:
        op.execute(
            sa.text(
                """
                INSERT INTO users
                    (id, twitch_id, twitch_username, twitch_display_name,
                     role, api_token)
                VALUES
                    (gen_random_uuid(), 'system:daily', 'speedfog_daily',
                     'Daily Seed', 'SYSTEM', NULL)
                ON CONFLICT (twitch_id) DO NOTHING
                """
            )
        )
    else:
        op.execute(
            sa.text(
                """
                INSERT OR IGNORE INTO users
                    (id, twitch_id, twitch_username, twitch_display_name,
                     role, api_token)
                VALUES
                    (:id, 'system:daily', 'speedfog_daily',
                     'Daily Seed', 'SYSTEM', NULL)
                """
            ).bindparams(id="00000000-0000-0000-0000-000000000001")
        )


def downgrade() -> None:
    op.execute(sa.text("DELETE FROM users WHERE twitch_id = 'system:daily'"))
    op.drop_table("daily_seed_schedule")
    op.alter_column(
        "users",
        "api_token",
        existing_type=sa.String(length=100),
        nullable=False,
    )
    op.drop_index("ix_races_daily_date", table_name="races")
    op.drop_index(
        "uq_races_daily_date",
        table_name="races",
        postgresql_where=sa.text("daily_date IS NOT NULL"),
        sqlite_where=sa.text("daily_date IS NOT NULL"),
    )
    op.drop_column("races", "exclude_from_elo")
    op.drop_column("races", "daily_date")
