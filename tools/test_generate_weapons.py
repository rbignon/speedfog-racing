"""Tests for generate_weapons.py (game_inspect dump parsing + catalogue rules)."""

from __future__ import annotations

import json

import pytest
from generate_weapons import (
    build_catalogue,
    dump_catalogue,
    main,
    parse_fmg,
    parse_params,
)

# Wine writes CRLF; the first row line carries one on purpose.
PARAMS = (
    "EquipParamWeapon: 6 rows\n"
    "  110000    wepType=33\r\n"
    "  1000000    wepType=1\n"
    "  1000100    wepType=1\n"
    "  3910000    wepType=5\n"
    "  50000000    wepType=81\n"
    "  67530000    wepType=93\n"
)

FMG = (
    "WeaponName.fmg                 110000     Unarmed\r\n"
    "WeaponName.fmg                 1000000    Dagger\r\n"
    "WeaponName.fmg                 1000100    Heavy Dagger\r\n"
    "WeaponName.fmg                 1030000    Miséricorde\r\n"
    "WeaponName.fmg                 3910000    [ERROR]\r\n"
    "WeaponName.fmg                 50000000   Arrow\r\n"
    "WeaponCaption.fmg              67530000   A sword from Idus.\r\n"
    "WeaponName_dlc01.fmg           67530000   Idus Sword\r\n"
)


def test_parse_params_reads_id_and_weptype() -> None:
    rows = parse_params(PARAMS)
    assert rows == {
        110000: 33,
        1000000: 1,
        1000100: 1,
        3910000: 5,
        50000000: 81,
        67530000: 93,
    }


def test_parse_fmg_keeps_weaponname_fmgs_only_and_drops_error_entries() -> None:
    names = parse_fmg(FMG)
    assert names == {
        110000: "Unarmed",
        1000000: "Dagger",
        1000100: "Heavy Dagger",
        1030000: "Miséricorde",
        50000000: "Arrow",
        67530000: "Idus Sword",
    }


def test_parse_fmg_first_name_wins_on_conflict(capsys) -> None:
    text = (
        "WeaponName.fmg                 1000000    Dagger\n"
        "WeaponName_dlc01.fmg           1000000    Dagger\n"
        "WeaponName_dlc02.fmg           1000000    Knife\n"
    )
    assert parse_fmg(text) == {1000000: "Dagger"}
    assert "1000000" in capsys.readouterr().err


def test_build_catalogue_applies_row_rules() -> None:
    catalogue = build_catalogue(parse_params(PARAMS), parse_fmg(FMG))
    # 110000 unarmed, 1000100 affinity row, 3910000 unnamed, 50000000 ammo.
    assert catalogue == {
        "1000000": {"name": "Dagger", "wep_type": 1},
        "67530000": {"name": "Idus Sword", "wep_type": 93},
    }


def test_dump_catalogue_matches_repository_format() -> None:
    # Keys are sorted as strings, not numerically ("1030000" before "2000000",
    # but "13510000" before "1400000"): this is the order of the checked-in file.
    text = dump_catalogue(
        {
            "2000000": {"name": "Longsword", "wep_type": 3},
            "1030000": {"name": "Miséricorde", "wep_type": 1},
        }
    )
    assert text == (
        "{\n"
        '  "1030000": {\n'
        '    "name": "Miséricorde",\n'
        '    "wep_type": 1\n'
        "  },\n"
        '  "2000000": {\n'
        '    "name": "Longsword",\n'
        '    "wep_type": 3\n'
        "  }\n"
        "}\n"
    )
    assert json.loads(text)["1030000"]["name"] == "Miséricorde"


@pytest.fixture
def dump_files(tmp_path):
    params = tmp_path / "params.txt"
    fmg = tmp_path / "fmg.txt"
    params.write_text(PARAMS, encoding="utf-8")
    fmg.write_text(FMG, encoding="utf-8")
    return params, fmg


def test_main_writes_catalogue_and_reports_changes(
    dump_files, tmp_path, capsys
) -> None:
    params, fmg = dump_files
    output = tmp_path / "weapons.json"
    output.write_text(
        dump_catalogue(
            {
                "1000000": {"name": "Dagger", "wep_type": 1},
                "2000000": {"name": "Longsword", "wep_type": 3},
                "67530000": {"name": "Idus Sword", "wep_type": 92},
            }
        ),
        encoding="utf-8",
    )

    assert main(["--params", str(params), "--fmg", str(fmg), "-o", str(output)]) == 0

    assert json.loads(output.read_text(encoding="utf-8")) == {
        "1000000": {"name": "Dagger", "wep_type": 1},
        "67530000": {"name": "Idus Sword", "wep_type": 93},
    }
    out = capsys.readouterr().out
    assert "2 weapons written" in out
    assert "removed: 2000000 Longsword" in out
    assert "changed: 67530000 Idus Sword (wep_type 93)" in out
    assert "added:" not in out


def test_main_refuses_empty_input_without_writing(dump_files, tmp_path) -> None:
    params, fmg = dump_files
    fmg.write_text(
        "WeaponCaption.fmg              1000000    Not a name\n", encoding="utf-8"
    )
    output = tmp_path / "weapons.json"

    assert main(["--params", str(params), "--fmg", str(fmg), "-o", str(output)]) == 1
    assert not output.exists()
