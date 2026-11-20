"""add relay to seeds

Revision ID: 5b9c2e7a4d13
Revises: 24e50b1ae2f9
Create Date: 2026-11-20 12:00:00.000000

Seeds get relay: the seed carries the relay block (a non-empty ``relay``
object in graph_json), set by the pool scan so the relay draw and the pool
counts filter on an indexed column instead of parsing graph_json. The
backfill checks the same condition in SQL, on PostgreSQL and SQLite.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b9c2e7a4d13"
down_revision: str | None = "24e50b1ae2f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# json_object_keys only sees an object: the CASE hands it NULL (no rows) otherwise.
_BACKFILL_POSTGRESQL = """
UPDATE seeds SET relay = true
WHERE EXISTS (
    SELECT 1 FROM json_object_keys(
      CASE WHEN json_typeof(graph_json -> 'relay') = 'object'
        THEN graph_json -> 'relay' END
    )
  )
"""

_BACKFILL_SQLITE = """
UPDATE seeds SET relay = 1
WHERE json_type(graph_json, '$.relay') = 'object'
  AND EXISTS (SELECT 1 FROM json_each(graph_json, '$.relay'))
"""


def _is_postgresql() -> bool:
    # The migration context, not op.get_bind(): it also answers in offline (--sql) mode.
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    with op.batch_alter_table("seeds") as batch_op:
        batch_op.add_column(sa.Column("relay", sa.Boolean(), nullable=False, server_default="0"))
        batch_op.create_index("ix_seeds_relay", ["relay"])
    op.execute(_BACKFILL_POSTGRESQL if _is_postgresql() else _BACKFILL_SQLITE)


def downgrade() -> None:
    with op.batch_alter_table("seeds") as batch_op:
        batch_op.drop_index("ix_seeds_relay")
        batch_op.drop_column("relay")
