"""Grace entity ID to graph node resolution.

Maps grace entity IDs (captured by the mod's warp hook during fast travel)
to graph nodes in the current seed. Uses graces.json from er-fog-vizu as the
static game-data mapping (grace_entity_id → zone_id), then finds the matching
node in graph_json via the node's `zones` array.

For map_id-based resolution, uses fog.txt (complete map→zone mapping) and
submaps.txt (position-based disambiguation) via the zone_resolver module.
"""

import json
import logging
from pathlib import Path
from typing import Any

from speedfog_racing.services.zone_resolver import (
    get_zones_for_map,
    resolve_zone_by_position,
)

logger = logging.getLogger(__name__)

_GRACES_FILE = Path(__file__).parent.parent.parent / "data" / "graces.json"


def load_graces_mapping() -> dict[str, dict[str, Any]]:
    """Load the grace entity ID → zone info mapping from graces.json.

    Returns a dict keyed by grace_entity_id (string), e.g.:
        {"10002950": {"grace_name": "Godrick the Grafted", "zone_id": "stormveil_godrick", ...}}
    """
    data = json.loads(_GRACES_FILE.read_text())
    mapping: dict[str, dict[str, Any]] = data["mapping"]
    return mapping


def resolve_grace_to_node(
    grace_entity_id: int,
    graph_json: dict[str, Any],
    graces_mapping: dict[str, dict[str, Any]],
) -> str | None:
    """Resolve a grace entity ID to a graph node_id.

    1. Look up grace_entity_id in graces_mapping → get zone_id
    2. Search graph_json nodes for one whose `zones` array contains zone_id
    3. Return node_id or None
    """
    if grace_entity_id == 0:
        return None

    grace_info = graces_mapping.get(str(grace_entity_id))
    if not grace_info:
        return None

    zone_id = grace_info.get("zone_id")
    if not zone_id:
        return None

    nodes = graph_json.get("nodes", {})
    for node_id, node_data in nodes.items():
        if isinstance(node_data, dict):
            zones = node_data.get("zones", [])
            if zone_id in zones:
                return str(node_id)

    return None


def resolve_zone_query(
    graph_json: dict[str, Any],
    graces_mapping: dict[str, dict[str, Any]],
    *,
    grace_entity_id: int | None = None,
    map_id: str | None = None,
    position: tuple[float, float, float] | None = None,
    play_region_id: int | None = None,  # reserved for future disambiguation
    zone_history: list[dict[str, Any]] | None = None,
) -> str | None:
    """Resolve a zone query to a graph node_id.

    Strategies (in order):
    1. Grace lookup (grace_entity_id → zone_id → node)
    2. Map-based lookup (map_id → fog.txt zone mapping → filter graph nodes)
       a. Get candidate zone_ids from fog.txt (complete map→zone mapping)
       b. If position available, use submaps.txt to narrow to one zone_id
       c. Find graph nodes whose zones intersect candidates
       d. If still ambiguous, narrow by zone_history (visited nodes only)
    3. None (ambiguous or no data)
    """
    # Strategy 1: grace lookup (highest confidence)
    if grace_entity_id is not None and grace_entity_id != 0:
        node_id = resolve_grace_to_node(grace_entity_id, graph_json, graces_mapping)
        if node_id is not None:
            return node_id

    # Strategy 2: map_id → fog.txt zone lookup + position disambiguation
    if map_id is not None:
        zone_ids_for_map = get_zones_for_map(map_id)

        # Use position to narrow candidates when available
        if position is not None and zone_ids_for_map:
            resolved = resolve_zone_by_position(map_id, *position)
            if resolved and resolved in zone_ids_for_map:
                zone_ids_for_map = {resolved}

        # Find graph nodes whose zones intersect candidates
        nodes = graph_json.get("nodes", {})
        matching: list[str] = []
        for nid, node_data in nodes.items():
            if isinstance(node_data, dict):
                zones = node_data.get("zones", [])
                if any(z in zone_ids_for_map for z in zones):
                    matching.append(nid)

        # Filter by history: player can only be in an explored zone
        # (zone_query is only sent on death/respawn/fast-travel, never on
        # fog gate traversal, so the target zone is always already explored)
        if matching and zone_history:
            explored = {e["node_id"] for e in zone_history if "node_id" in e}
            matching = [nid for nid in matching if nid in explored]

        if len(matching) == 1:
            return matching[0]

    return None
