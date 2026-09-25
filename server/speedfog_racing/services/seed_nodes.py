"""Cached per-seed projection of graph nodes.

A seed's ``graph_json`` averages ~120 KB of JSON, and decoding it is the
dominant cost of any code that walks many races. Most consumers only need
node membership and per-node metadata, so they read this projection instead.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from speedfog_racing.models import Seed


@dataclass(frozen=True)
class NodeDisplay:
    """Resolved per-node naming/type/zones from the most recent seed containing it.

    ``short_name`` is the last " - " segment (area prefix stripped), used by
    the top-5 panels. ``full_name`` is the unmodified display_name, used by
    the zone codex index/detail and as the merge key in
    ``_aggregate_zone_stats`` (``api/stats.py``, see there for why merging
    must use the full name).
    """

    short_name: str
    full_name: str
    type: str
    # A tuple, not a list: NodeDisplay instances live forever in the shared
    # seed projection cache, so their contents must be structurally immutable.
    zones: tuple[str, ...]
    # 0-indexed layer in the owning seed's graph. Meaningful per seed (the
    # same cluster can sit at different layers across seeds), so read it from
    # the participant's own SeedNodes, never from the merged node_display.
    layer: int
    # Short boss label for the boss stats page: the node's boss_name
    # (canonical name from ItemRandomizer's enemy.txt) when present, else the
    # display_name, with the area prefix pre-stripped. Bosses are randomized
    # per seed, so like ``layer`` this must be read from the participant's
    # own SeedNodes, never from the merged node_display.
    boss_name: str


@dataclass(frozen=True)
class SeedNodes:
    """Cached projection of one seed's graph nodes.

    Holds every node of the graph with its display metadata, a few KB out of
    a graph_json that can weigh hundreds of KB. ``created_at`` orders seeds
    for most-recent display resolution. ``total_nodes`` is the graph's own
    ``total_nodes`` field (None on graphs that predate it).
    """

    created_at: datetime
    nodes: dict[str, NodeDisplay]
    total_nodes: int | None


# Seed graphs are immutable once the seed is consumed, so projections are
# cached in-process forever: no TTL, no invalidation. Entries are a few KB
# each and only accumulate at the pace new seeds get raced or trained on.
_seed_nodes_cache: dict[Any, SeedNodes] = {}

# Cold loads (e.g. the first call after a restart) can miss hundreds of seeds.
# Reading them in batches bounds the decoded graphs held in memory at once and
# yields to the event loop between batches.
_LOAD_BATCH_SIZE = 50


def project_seed_nodes(created_at: datetime, graph_json: dict[str, Any]) -> SeedNodes:
    """Extract the SeedNodes projection from a raw graph_json."""
    nodes: dict[str, NodeDisplay] = {}
    for nid, meta in graph_json.get("nodes", {}).items():
        full_name = meta.get("display_name", nid)
        short_name = full_name.rsplit(" - ", 1)[-1]
        nodes[nid] = NodeDisplay(
            short_name=short_name,
            full_name=full_name,
            type=meta.get("type", ""),
            zones=tuple(meta.get("zones", [])),
            layer=meta.get("layer") or 0,
            boss_name=(meta.get("boss_name") or full_name).rsplit(" - ", 1)[-1],
        )
    return SeedNodes(created_at=created_at, nodes=nodes, total_nodes=graph_json.get("total_nodes"))


async def load_seed_nodes(db: AsyncSession, seed_ids: Iterable[Any]) -> dict[Any, SeedNodes]:
    """Return the SeedNodes projection of each requested seed, keyed by id.

    Only seeds missing from the cache are read (and their graph_json decoded)
    from the database. Unknown ids are absent from the result.
    """
    wanted = set(seed_ids)
    missing = [sid for sid in wanted if sid not in _seed_nodes_cache]
    for start in range(0, len(missing), _LOAD_BATCH_SIZE):
        batch = missing[start : start + _LOAD_BATCH_SIZE]
        seed_rows = (
            await db.execute(
                select(Seed.id, Seed.created_at, Seed.graph_json).where(Seed.id.in_(batch))
            )
        ).all()
        for sid, created_at, graph_json in seed_rows:
            _seed_nodes_cache[sid] = project_seed_nodes(created_at, graph_json)
    return {sid: _seed_nodes_cache[sid] for sid in wanted if sid in _seed_nodes_cache}
