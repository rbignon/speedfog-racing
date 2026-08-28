#!/usr/bin/env python3
"""Generate server/data/weapons.json from Elden Ring game data.

The catalogue maps every player weapon's base ``EquipParamWeapon`` row ID to
its English name and ``wepType``. It is derived from two dumps produced by
speedfog's ``game_inspect`` tool (Wine on Linux), run against the current
game version:

    cd $SPEEDFOG_PATH/tools/game_inspect
    wine publish/win-x64/game_inspect.exe dump-param <game>/regulation.bin \\
        EquipParamWeapon --all --field wepType \\
        --defs ../../writer/FogModWrapper/eldendata/Defs > params.txt
    wine publish/win-x64/game_inspect.exe dump-fmg \\
        <game>/msg/engus/item_dlc02.msgbnd.dcx > fmg.txt

Usage:
    python tools/generate_weapons.py --params params.txt --fmg fmg.txt

Rows are kept when they are a base row (no affinity or upgrade digits), have a
``WeaponName`` FMG entry, and are not Unarmed or ammunition (arrows and bolts
live in ChrAsm slots the mod does not read, see docs/WEAPONS_TRACKING.md).
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT = ROOT / "server" / "data" / "weapons.json"

# EquipParamWeapon.wepType values never reported as a held weapon.
WEP_TYPE_UNARMED = 33
WEP_TYPE_AMMO = frozenset({81, 83, 85, 86})  # Arrow, Greatarrow, Bolt, BallistaBolt
EXCLUDED_WEP_TYPES = WEP_TYPE_AMMO | {WEP_TYPE_UNARMED}

# Affinity (affinity index * 100, Standard 0 up to Occult 1200) and upgrade
# level (0..25) are folded into the row ID; the base row ends with four zeros.
BASE_ROW_MODULUS = 10_000

_PARAM_LINE = re.compile(r"^\s+(\d+)\s.*\bwepType=(\d+)")
_FMG_LINE = re.compile(r"^WeaponName(?:_dlc\d+)?\.fmg\s+(\d+)\s+(.*)$")
_FMG_MISSING = "[ERROR]"


def parse_params(text: str) -> dict[int, int]:
    """Row ID -> wepType from ``dump-param --all --field wepType`` output."""
    rows: dict[int, int] = {}
    for line in text.splitlines():
        m = _PARAM_LINE.match(line)
        if m:
            rows[int(m.group(1))] = int(m.group(2))
    return rows


def parse_fmg(text: str) -> dict[int, str]:
    """Row ID -> name from ``dump-fmg`` output, ``WeaponName*`` FMGs only.

    A msgbnd holds several WeaponName FMGs (base, _dlc01, _dlc02). No ID is
    named differently by two of them in practice (checked on 1.16 and 1.17),
    so the first real entry wins and a conflicting later entry is reported on
    stderr for a human to arbitrate rather than silently resolved.
    """
    names: dict[int, str] = {}
    for line in text.splitlines():
        m = _FMG_LINE.match(line)
        if not m:
            continue
        row_id, name = int(m.group(1)), m.group(2).rstrip()
        if not name or name == _FMG_MISSING:
            continue
        if row_id not in names:
            names[row_id] = name
        elif names[row_id] != name:
            print(
                f"warning: {row_id} named {names[row_id]!r} and {name!r}, keeping the first",
                file=sys.stderr,
            )
    return names


def build_catalogue(
    rows: dict[int, int], names: dict[int, str]
) -> dict[str, dict[str, object]]:
    """Base rows with a name and a tracked wepType, keyed by row ID string."""
    catalogue: dict[str, dict[str, object]] = {}
    for row_id, wep_type in rows.items():
        if row_id % BASE_ROW_MODULUS or wep_type in EXCLUDED_WEP_TYPES:
            continue
        name = names.get(row_id)
        if name is None:
            continue
        catalogue[str(row_id)] = {"name": name, "wep_type": wep_type}
    return catalogue


def dump_catalogue(catalogue: dict[str, dict[str, object]]) -> str:
    return json.dumps(catalogue, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--params",
        required=True,
        type=Path,
        help="dump-param --all --field wepType output",
    )
    parser.add_argument(
        "--fmg",
        required=True,
        type=Path,
        help="dump-fmg output of item_dlc02.msgbnd.dcx",
    )
    parser.add_argument("-o", "--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args(argv)

    rows = parse_params(args.params.read_text(encoding="utf-8"))
    names = parse_fmg(args.fmg.read_text(encoding="utf-8"))
    if not rows or not names:
        print(
            "error: no EquipParamWeapon rows or WeaponName entries parsed",
            file=sys.stderr,
        )
        return 1

    catalogue = build_catalogue(rows, names)
    previous: dict[str, object] = {}
    if args.output.exists():
        previous = json.loads(args.output.read_text(encoding="utf-8"))
    args.output.write_text(dump_catalogue(catalogue), encoding="utf-8")

    added = sorted(set(catalogue) - set(previous), key=int)
    removed = sorted(set(previous) - set(catalogue), key=int)
    changed = sorted(
        (k for k in set(catalogue) & set(previous) if catalogue[k] != previous[k]),
        key=int,
    )
    print(f"{len(catalogue)} weapons written to {args.output}")
    for label, ids in (("added", added), ("removed", removed), ("changed", changed)):
        for k in ids:
            entry = catalogue.get(k) or previous[k]
            print(f"  {label}: {k} {entry['name']} (wep_type {entry['wep_type']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
