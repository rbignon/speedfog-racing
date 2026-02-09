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
