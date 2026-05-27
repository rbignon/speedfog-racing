"""EquipParamWeapon ID -> name/type lookup and the filter applied to mod-reported
equipped weapons.

The mod sends raw runtime weapon IDs (param row ID + upgrade level) in each
status_update. The server strips the upgrade level, looks the base ID up in
``weapons.json``, and drops weapons whose ``wep_type`` is in
``EXCLUDED_WEP_TYPES`` (staves, seals, shields, torches).

Source for the catalogue and WepType numeric values: TarnishedTool.
"""

import json
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_WEAPONS_FILE = Path(__file__).parent.parent.parent / "data" / "weapons.json"

EXCLUDED_WEP_TYPES: frozenset[int] = frozenset(
    {
        57,  # Staff
        61,  # Seal
        65,  # SmallShield
        67,  # MediumShield
        69,  # Greatshield
        87,  # Torch
        90,  # ThrustingShield
    }
)


@dataclass(frozen=True, slots=True)
class WeaponInfo:
    name: str
    wep_type: int


def _load_weapons() -> dict[int, WeaponInfo]:
    raw = json.loads(_WEAPONS_FILE.read_text(encoding="utf-8"))
    weapons = {
        int(k): WeaponInfo(name=v["name"], wep_type=int(v["wep_type"])) for k, v in raw.items()
    }
    logger.info("Loaded %d weapons from %s", len(weapons), _WEAPONS_FILE)
    return weapons


WEAPONS: dict[int, WeaponInfo] = _load_weapons()


def filter_equipped(raw_id: int | None) -> int | None:
    """Return the raw runtime weapon ID if it is a tracked melee/ranged weapon,
    ``None`` otherwise (empty hand, unknown ID, or excluded type).

    Strips the upgrade level (rows are spaced at multiples of 100) before lookup,
    but returns the raw ID with the upgrade preserved.
    """
    if raw_id is None or raw_id <= 0:
        return None
    base_id = raw_id - (raw_id % 100)
    info = WEAPONS.get(base_id)
    if info is None or info.wep_type in EXCLUDED_WEP_TYPES:
        return None
    return raw_id
