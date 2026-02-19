"""Layer computation from seed graph data."""

from typing import Any


def _format_zone_name(zone_id: str) -> str:
    """Convert zone_id like 'volcano_drawingroom' to 'Volcano Drawingroom'."""
    return zone_id.replace("_", " ").title()


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
    Falls back to the top-level ``start_node`` key if no node has type "start".
    """
    nodes: dict[str, Any] = graph_json.get("nodes", {})
    for node_id, node_data in nodes.items():
        if isinstance(node_data, dict) and node_data.get("type") == "start":
            return node_id
    # Fallback: top-level start_node key
    fallback = graph_json.get("start_node")
    if isinstance(fallback, str) and fallback in nodes:
        return fallback
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

    original_tier = node_data.get("original_tier")
    if isinstance(original_tier, int | float):
        original_tier = int(original_tier)
    else:
        original_tier = None

    # Build set of discovered node_ids from zone_history
    discovered_ids: set[str] = set()
    if zone_history:
        for entry in zone_history:
            nid = entry.get("node_id")
            if isinstance(nid, str):
                discovered_ids.add(nid)

    # Build exits list
    zones = node_data.get("zones", [])
    primary_zone = zones[0] if zones else None

    exits: list[dict[str, Any]] = []
    for exit_data in node_data.get("exits", []):
        if not isinstance(exit_data, dict):
            continue
        to_id = exit_data.get("to")
        text = exit_data.get("text", "")
        from_zone = exit_data.get("from")
        # Pass sub-zone origin separately so i18n can translate it.
        # ``from_zone`` is consumed by translate_zone_update() which
        # translates it and assembles it into ``text`` as "[Zone Name]".
        from_zone_label: str | None = None
        if from_zone and primary_zone and from_zone != primary_zone:
            from_zone_label = _format_zone_name(from_zone)
        to_node = nodes.get(to_id, {}) if isinstance(to_id, str) else {}
        to_name = to_node.get("display_name", to_id) if isinstance(to_node, dict) else str(to_id)
        ex: dict[str, Any] = {
            "text": text,
            "to_name": to_name,
            "discovered": isinstance(to_id, str) and to_id in discovered_ids,
        }
        if from_zone_label:
            ex["from_zone"] = from_zone_label
        exits.append(ex)

    return {
        "type": "zone_update",
        "node_id": node_id,
        "display_name": display_name,
        "tier": tier,
        "original_tier": original_tier,
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
