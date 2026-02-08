"""Layer computation from seed graph data."""

from typing import Any


def get_layer_for_zone(zone: str, graph_json: dict[str, Any]) -> int:
    """Look up layer for a zone/area name from area_tiers.

    Returns 0 if zone not found in area_tiers or if area_tiers is missing.
    """
    area_tiers: dict[str, int] = graph_json.get("area_tiers", {})
    return area_tiers.get(zone, 0)


def get_node_for_zone(zone: str, graph_json: dict[str, Any]) -> str | None:
    """Find the node_id containing the given zone in graph_json["nodes"].

    Searches the nodes dict for a node whose "zones" list contains the zone.
    Returns None if not found.
    """
    nodes: dict[str, Any] = graph_json.get("nodes", {})
    for node_id, node_data in nodes.items():
        if isinstance(node_data, dict):
            zones = node_data.get("zones", [])
            if zone in zones:
                return node_id
    return None


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
