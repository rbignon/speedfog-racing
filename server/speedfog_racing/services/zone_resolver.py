"""Zone resolution from map_id + position using fog.txt and submaps.txt.

Provides a complete map_id → zone_id mapping (fog.txt) and position-based
disambiguation (submaps.txt) for maps that contain multiple zones (e.g.,
Leyndell Royal Capital m11_00_00_00 has leyndell, leyndell_sanctuary, etc.).

This replaces the incomplete graces.json reverse-lookup in resolve_zone_query(),
which missed zones without graces (38% of graces have map_id: null).
"""

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)

_DATA_DIR = Path(__file__).parent.parent.parent / "data"


@dataclass
class PositionRule:
    """A position-based rule for zone disambiguation within a map."""

    area: str
    name: str = ""
    x_above: float | None = None
    x_below: float | None = None
    y_above: float | None = None
    y_below: float | None = None
    z_above: float | None = None
    z_below: float | None = None

    def matches(self, x: float, y: float, z: float) -> bool:
        """Check if position matches all conditions of this rule."""
        if self.x_above is not None and x <= self.x_above:
            return False
        if self.x_below is not None and x >= self.x_below:
            return False
        if self.y_above is not None and y <= self.y_above:
            return False
        if self.y_below is not None and y >= self.y_below:
            return False
        if self.z_above is not None and z <= self.z_above:
            return False
        return not (self.z_below is not None and z >= self.z_below)


@dataclass
class MapRules:
    """Position rules for a single map_id."""

    rules: list[PositionRule] = field(default_factory=list)
    default_area: str | None = None


# Module-level caches, populated on first access
_map_to_zones: dict[str, set[str]] | None = None
_map_rules: dict[str, MapRules] | None = None


def _ensure_loaded() -> None:
    """Load data files if not already loaded."""
    global _map_to_zones, _map_rules
    if _map_to_zones is not None:
        return
    _map_to_zones = {}
    _map_rules = {}
    _load_fog(_DATA_DIR / "fog.txt")
    _load_submaps(_DATA_DIR / "submaps.txt")
    logger.info(
        "zone_resolver: loaded %d map→zone entries, %d map position rules",
        len(_map_to_zones),
        len(_map_rules),
    )


def _load_fog(path: Path) -> None:
    """Parse fog.txt for Name: + Maps: fields → map_id → zone_id mapping."""
    assert _map_to_zones is not None
    if not path.exists():
        logger.warning("fog.txt not found at %s", path)
        return

    current_name: str | None = None
    in_areas_section = False

    for line in path.read_text().split("\n"):
        stripped = line.strip()
        indent = len(line) - len(line.lstrip())

        # Track top-level sections (Areas:, FogGates:, etc.)
        if indent == 0 and stripped.endswith(":") and not stripped.startswith("-"):
            in_areas_section = stripped == "Areas:"
            current_name = None
            continue

        if stripped.startswith("- Name:") and in_areas_section:
            current_name = stripped.removeprefix("- Name:").strip()
        elif stripped.startswith("Maps:") and current_name and indent <= 2:
            map_ids = stripped.removeprefix("Maps:").strip().split()
            for map_id in map_ids:
                if map_id not in _map_to_zones:
                    _map_to_zones[map_id] = set()
                _map_to_zones[map_id].add(current_name)


def _load_submaps(path: Path) -> None:
    """Parse submaps.txt for position-based disambiguation rules."""
    assert _map_rules is not None
    if not path.exists():
        logger.warning("submaps.txt not found at %s", path)
        return

    current_map: str | None = None
    current_areas: list[PositionRule] = []

    def finalize() -> None:
        if current_map is None or _map_rules is None:
            return
        rules = MapRules()
        for area in current_areas:
            if not area.area:
                continue
            has_condition = any(
                [
                    area.x_above is not None,
                    area.x_below is not None,
                    area.y_above is not None,
                    area.y_below is not None,
                    area.z_above is not None,
                    area.z_below is not None,
                ]
            )
            if has_condition:
                rules.rules.append(area)
            else:
                rules.default_area = area.area
        _map_rules[current_map] = rules

    for line in path.read_text().split("\n"):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue

        if line.startswith("- Map: "):
            finalize()
            current_map = stripped.removeprefix("- Map: ").strip()
            current_areas = []
        elif stripped.startswith("- Name:"):
            current_areas.append(
                PositionRule(area="", name=stripped.removeprefix("- Name:").strip())
            )
        elif stripped.startswith("Area:") and current_areas:
            current_areas[-1].area = stripped.removeprefix("Area:").strip()
        elif stripped.startswith("XAbove:") and current_areas:
            current_areas[-1].x_above = float(stripped.removeprefix("XAbove:").strip())
        elif stripped.startswith("XBelow:") and current_areas:
            current_areas[-1].x_below = float(stripped.removeprefix("XBelow:").strip())
        elif stripped.startswith("YAbove:") and current_areas:
            current_areas[-1].y_above = float(stripped.removeprefix("YAbove:").strip())
        elif stripped.startswith("YBelow:") and current_areas:
            current_areas[-1].y_below = float(stripped.removeprefix("YBelow:").strip())
        elif stripped.startswith("ZAbove:") and current_areas:
            current_areas[-1].z_above = float(stripped.removeprefix("ZAbove:").strip())
        elif stripped.startswith("ZBelow:") and current_areas:
            current_areas[-1].z_below = float(stripped.removeprefix("ZBelow:").strip())

    finalize()


def get_zones_for_map(map_id: str) -> set[str]:
    """All zone_ids that exist in this map_id (from fog.txt)."""
    _ensure_loaded()
    assert _map_to_zones is not None
    return _map_to_zones.get(map_id, set())


def resolve_zone_by_position(map_id: str, x: float, y: float, z: float) -> str | None:
    """Narrow to specific zone_id using submaps.txt position rules.

    Returns None if no rules exist for this map or no rule matches.
    """
    _ensure_loaded()
    assert _map_rules is not None
    rules = _map_rules.get(map_id)
    if rules is None:
        return None

    for rule in rules.rules:
        if rule.matches(x, y, z):
            return rule.area

    return rules.default_area
