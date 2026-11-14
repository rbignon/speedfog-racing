"""clear race_items on seeds older than graph.json 4.12

Revision ID: 24e50b1ae2f9
Revises: a368de6f2bcf
Create Date: 2026-11-14 22:00:00.000000

Protocol 1.13 reads the race items catalog of graph.json 4.12: a ``goods``
object and a non-empty ``items`` object. The seeds generated before it carry
a flat ``{item_key: entry}`` catalog (one goods per item), which the scan and
the a368de6f2bcf backfill flagged ``race_items``: items races would still draw
them, then grant nothing, since the server no longer reads that catalog. This
clears the flag on every flagged seed whose graph lacks the 4.12 shape.

The shape check is pinned here, not imported: the live one may evolve. Only
flagged seeds are read, their graphs a batch at a time, so a large pool never
sits in memory at once.

The downgrade does nothing: which seeds were cleared is not recorded, and
only a server older than 1.13 could use them. Should one ever be restored,
run a368de6f2bcf's backfill again by hand.
"""

import logging
from collections.abc import Sequence
from typing import Any

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "24e50b1ae2f9"
down_revision: str | None = "a368de6f2bcf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

log = logging.getLogger(f"alembic.migration.{revision}")

BATCH_SIZE = 200

seeds = sa.table(
    "seeds",
    sa.column("id", sa.Uuid),
    sa.column("graph_json", sa.JSON),
    sa.column("race_items", sa.Boolean),
)


def has_4_12_catalog(graph_json: object) -> bool:
    """The graph.json 4.12 race items shape: the plugin enabled, and a
    ``race_items`` object holding a ``goods`` object and a non-empty ``items``
    object."""
    if not isinstance(graph_json, dict):
        return False
    plugins = graph_json.get("plugins")
    plugin = plugins.get("race_items") if isinstance(plugins, dict) else None
    if not isinstance(plugin, dict) or plugin.get("enabled") is not True:
        return False
    catalog = graph_json.get("race_items")
    if not isinstance(catalog, dict):
        return False
    goods, items = catalog.get("goods"), catalog.get("items")
    return isinstance(goods, dict) and isinstance(items, dict) and len(items) > 0


def clear_pre_4_12_seeds(connection: Any) -> int:
    """Clear ``race_items`` on the flagged seeds without the 4.12 catalog.

    Returns the number of seeds cleared.
    """
    flagged = list(
        connection.execute(sa.select(seeds.c.id).where(seeds.c.race_items.is_(True))).scalars()
    )
    stale: list[Any] = []
    for start in range(0, len(flagged), BATCH_SIZE):
        batch = flagged[start : start + BATCH_SIZE]
        rows = connection.execute(
            sa.select(seeds.c.id, seeds.c.graph_json).where(seeds.c.id.in_(batch))
        )
        stale.extend(seed_id for seed_id, graph_json in rows if not has_4_12_catalog(graph_json))
    for start in range(0, len(stale), BATCH_SIZE):
        connection.execute(
            sa.update(seeds)
            .where(seeds.c.id.in_(stale[start : start + BATCH_SIZE]))
            .values(race_items=False)
        )
    return len(stale)


def upgrade() -> None:
    cleared = clear_pre_4_12_seeds(op.get_bind())
    log.info("Cleared race_items on %d seeds older than graph.json 4.12", cleared)


def downgrade() -> None:
    # No-op: the cleared seeds are not recorded (see the module docstring).
    pass
