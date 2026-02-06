"""Layer computation from seed graph data."""

from typing import Any


def get_layer_for_zone(zone: str, graph_json: dict[str, Any]) -> int:
    """Look up layer for a zone/area name from area_tiers.

    Returns 0 if zone not found in area_tiers or if area_tiers is missing.
    """
    area_tiers: dict[str, int] = graph_json.get("area_tiers", {})
    return area_tiers.get(zone, 0)
