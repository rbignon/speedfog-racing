"""recompute seeds.relay for the 4.16 block

Revision ID: a004a9973fb3
Revises: a4898d1850a8
Create Date: 2026-11-23 23:36:46.256137

A seed is a relay seed only with the graph.json 4.16 block, told here by the
keys that first appear in it: a ``relay`` object holding a ``loot`` object
(possibly empty) and an integer ``roundtable_warp_flag``. Earlier blocks, and
a seed exported without a build (no ``loot``), no longer qualify. This
recomputes ``seeds.relay`` with that rule, in SQL on ``graph_json`` the way
``5b9c2e7a4d13`` backfilled the column, on PostgreSQL and SQLite.

The previous rule, a non-empty ``relay`` object, accepted every block the new
one accepts, so the upgrade can only clear the column: it reads the rows
marked relay alone (through ``ix_seeds_relay``) and writes those the new rule
rejects. The downgrade restores the previous rule on every row.
"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a004a9973fb3"
down_revision: str | None = "a4898d1850a8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# json_typeof of a missing key is NULL: COALESCE turns the comparison into false.
_UPGRADE_POSTGRESQL = """
UPDATE seeds SET relay = false
WHERE relay
  AND NOT COALESCE(
    json_typeof(graph_json -> 'relay') = 'object'
    AND json_typeof(graph_json -> 'relay' -> 'loot') = 'object'
    AND json_typeof(graph_json -> 'relay' -> 'roundtable_warp_flag') = 'number',
    false
  )
"""

_UPGRADE_SQLITE = """
UPDATE seeds SET relay = 0
WHERE relay = 1
  AND NOT COALESCE(
    json_type(graph_json, '$.relay') = 'object'
    AND json_type(graph_json, '$.relay.loot') = 'object'
    AND json_type(graph_json, '$.relay.roundtable_warp_flag') = 'integer',
    0
  )
"""

# json_object_keys only sees an object: the CASE hands it NULL (no rows) otherwise.
_DOWNGRADE_POSTGRESQL = """
UPDATE seeds SET relay = EXISTS (
    SELECT 1 FROM json_object_keys(
      CASE WHEN json_typeof(graph_json -> 'relay') = 'object'
        THEN graph_json -> 'relay' END
    )
)
"""

_DOWNGRADE_SQLITE = """
UPDATE seeds SET relay = COALESCE(
    json_type(graph_json, '$.relay') = 'object'
    AND EXISTS (SELECT 1 FROM json_each(graph_json, '$.relay')),
    0
)
"""


def _is_postgresql() -> bool:
    # The migration context, not op.get_bind(): it also answers in offline (--sql) mode.
    return op.get_context().dialect.name == "postgresql"


def upgrade() -> None:
    op.execute(_UPGRADE_POSTGRESQL if _is_postgresql() else _UPGRADE_SQLITE)


def downgrade() -> None:
    op.execute(_DOWNGRADE_POSTGRESQL if _is_postgresql() else _DOWNGRADE_SQLITE)
