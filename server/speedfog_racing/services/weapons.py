"""EquipParamWeapon ID -> name/type lookup and the filter applied to mod-reported
equipped weapons.

The mod sends raw runtime weapon IDs (param row ID + upgrade level) in each
status_update. The server strips the upgrade level, looks the base ID up in
``weapons.csv``, and drops weapons whose ``wep_type`` is in ``EXCLUDED_WEP_TYPES``
(staves, seals, shields, arrows, bolts, torches).

Source for both the CSV and the WepType numeric values: TarnishedTool.
"""

import csv
import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

_WEAPONS_FILE = Path(__file__).parent.parent.parent / "data" / "weapons.csv"

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
# Ammo wep_types (81 Arrow, 83 Greatarrow, 85 Bolt, 86 BallistaBolt) are not in
# weapons.csv: arrows and bolts live in distinct ChrAsm slots (PrimaryArrow/Bolt)
# which we do not read, so they can never reach this filter.


@dataclass(frozen=True, slots=True)
class WeaponInfo:
    name: str
    wep_type: int


def _load_weapons() -> dict[int, WeaponInfo]:
    weapons: dict[int, WeaponInfo] = {}
    with _WEAPONS_FILE.open(encoding="utf-8", newline="") as f:
        reader = csv.reader(f)
        for row in reader:
            if not row or row[0].startswith("#"):
                continue
            if len(row) < 3:
                continue
            try:
                weapon_id = int(row[0])
                wep_type = int(row[2])
            except ValueError:
                continue
            weapons[weapon_id] = WeaponInfo(name=row[1], wep_type=wep_type)
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
