"""add race_items to seeds

Revision ID: a368de6f2bcf
Revises: a7d3e91f4b26
Create Date: 2026-11-12 21:00:00.000000

Seeds get race_items: the seed carries the race items plugin (plugin enabled
and a non-empty catalog object), set by the pool scan so the items draw and
the pool counts filter on an indexed column instead of parsing graph_json.
The backfill checks the same condition in SQL, on PostgreSQL and SQLite.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a368de6f2bcf"
down_revision: str | None = "a7d3e91f4b26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# graph_json is a json column: the text of a JSON true is "true" (a string
# "true" reads with its quotes), and json_object_keys only sees an object.
_BACKFILL_POSTGRESQL = """
UPDATE seeds SET race_items = true
WHERE (graph_json #> '{plugins,race_items,enabled}')::text = 'true'
  AND EXISTS (
    SELECT 1 FROM json_object_keys(
      CASE WHEN json_typeof(graph_json -> 'race_items') = 'object'
        THEN graph_json -> 'race_items' END
    )
  )
"""

_BACKFILL_SQLITE = """
UPDATE seeds SET race_items = 1
WHERE json_type(graph_json, '$.plugins.race_items.enabled') = 'true'
  AND json_type(graph_json, '$.race_items') = 'object'
  AND EXISTS (SELECT 1 FROM json_each(graph_json, '$.race_items'))
"""


def _is_postgresql() -> bool:
    # The migration context, not op.get_bind(): it also answers in offline (--sql) mode.
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    with op.batch_alter_table("seeds") as batch_op:
        batch_op.add_column(
            sa.Column("race_items", sa.Boolean(), nullable=False, server_default="0")
        )
        batch_op.create_index("ix_seeds_race_items", ["race_items"])
    op.execute(_BACKFILL_POSTGRESQL if _is_postgresql() else _BACKFILL_SQLITE)


def downgrade() -> None:
    with op.batch_alter_table("seeds") as batch_op:
        batch_op.drop_index("ix_seeds_race_items")
        batch_op.drop_column("race_items")
