"""EquipParamWeapon ID -> name/type lookup and the filter applied to mod-reported
equipped weapons.

The mod sends raw runtime weapon IDs (param row ID + affinity + upgrade level) in
each status_update. The server strips the affinity and upgrade level, looks the base
ID up in ``weapons.json``, and drops weapons whose ``wep_type`` is in
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

    Strips the low three digits (affinity in the hundreds, upgrade level in
    the tens and units) before lookup, but returns the raw ID with the
    affinity and upgrade preserved.
    """
    if raw_id is None or raw_id <= 0:
        return None
    base_id = raw_id - (raw_id % 1000)
    info = WEAPONS.get(base_id)
    if info is None or info.wep_type in EXCLUDED_WEP_TYPES:
        return None
    return raw_id


def bump_combo(
    weapons_list: list[dict[str, object]],
    left: int | None,
    right: int | None,
) -> list[dict[str, object]]:
    """Return a new list with the (left, right) combo bumped by one tick.

    Canonicalisation rules (Option B from the design spec):
    - Both sides ``None``: return the list unchanged.
    - Exactly one side a tracked id ``X``: the combo key is ``[X]``. Both
      ``(None, X)`` and ``(X, None)`` increment the same single-weapon entry,
      hand information is intentionally dropped.
    - Both sides tracked ids ``X, Y``: the combo key is ``[X, Y]`` in
      mod-reported order (left, right). ``[X, Y]`` and ``[Y, X]`` are
      different combos.

    The caller normally skips invoking this helper when both inputs are
    ``None``; the no-op return is defensive.
    """
    if left is None and right is None:
        return weapons_list
    if left is None:
        ids: list[int] = [right]  # type: ignore[list-item]
    elif right is None:
        ids = [left]
    else:
        ids = [left, right]

    out = [dict(entry) for entry in weapons_list]
    for entry in out:
        if entry.get("ids") == ids:
            ticks_val: object = entry.get("ticks", 0)
            if isinstance(ticks_val, int):
                entry["ticks"] = ticks_val + 1
            else:
                entry["ticks"] = int(ticks_val) + 1  # type: ignore[call-overload]
            return out
    out.append({"ids": ids, "ticks": 1})
    return out
