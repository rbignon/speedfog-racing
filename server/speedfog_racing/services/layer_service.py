"""Layer computation from seed graph data."""

from typing import Any


def get_layer_for_node(node_id: str, graph_json: dict[str, Any]) -> int:
    """Get layer for a node_id from graph_json nodes.

    Returns 0 if node not found or if layer key is missing.
    """
    nodes: dict[str, Any] = graph_json.get("nodes", {})
    node_data = nodes.get(node_id, {})
    if isinstance(node_data, dict):
        layer = node_data.get("layer", 0)
        return int(layer) if isinstance(layer, int | float) else 0
    return 0


def get_start_node(graph_json: dict[str, Any]) -> str | None:
    """Find the start node (type == "start") in graph_json.

    Returns the node_id or None if not found.
    """
    nodes: dict[str, Any] = graph_json.get("nodes", {})
    for node_id, node_data in nodes.items():
        if isinstance(node_data, dict) and node_data.get("type") == "start":
            return node_id
    return None


def compute_zone_update(
    node_id: str,
    graph_json: dict[str, Any],
    zone_history: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    """Compute a zone_update message payload for a given node.

    Returns a dict matching ZoneUpdateMessage shape, or None if node not found.
    """
    nodes: dict[str, Any] = graph_json.get("nodes", {})
    node_data = nodes.get(node_id)
    if not isinstance(node_data, dict):
        return None

    display_name = node_data.get("display_name", node_id)
    tier = node_data.get("tier")
    if isinstance(tier, int | float):
        tier = int(tier)
    else:
        tier = None

    # Build set of discovered node_ids from zone_history
    discovered_ids: set[str] = set()
    if zone_history:
        for entry in zone_history:
            nid = entry.get("node_id")
            if isinstance(nid, str):
                discovered_ids.add(nid)

    # Build exits list
    exits: list[dict[str, Any]] = []
    for exit_data in node_data.get("exits", []):
        if not isinstance(exit_data, dict):
            continue
        to_id = exit_data.get("to")
        text = exit_data.get("text", "")
        to_node = nodes.get(to_id, {}) if isinstance(to_id, str) else {}
        to_name = to_node.get("display_name", to_id) if isinstance(to_node, dict) else str(to_id)
        exits.append(
            {
                "text": text,
                "to_name": to_name,
                "discovered": isinstance(to_id, str) and to_id in discovered_ids,
            }
        )

    return {
        "type": "zone_update",
        "node_id": node_id,
        "display_name": display_name,
        "tier": tier,
        "exits": exits,
    }


def get_tier_for_node(node_id: str, graph_json: dict[str, Any]) -> int | None:
    """Get tier for a node_id from graph_json nodes.

    Returns None if node not found or if tier key is missing.
    """
    nodes: dict[str, Any] = graph_json.get("nodes", {})
    node_data = nodes.get(node_id, {})
    if isinstance(node_data, dict):
        tier = node_data.get("tier")
        if isinstance(tier, int | float):
            return int(tier)
    return None
