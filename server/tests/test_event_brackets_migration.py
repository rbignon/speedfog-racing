"""The data migration that wraps an event's flat stage list into brackets."""

from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "b8e2f4a6c1d3_wrap_event_stages_in_brackets.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("brackets_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load()


def _stage(key: str, kind: str, **fields: Any) -> dict[str, Any]:
    # Stored documents carry every field, null when unset (model_dump output).
    return {
        "key": key,
        "label": key.replace("_", " ").title(),
        "kind": kind,
        "date": None,
        "races": 3,
        "seeds": None,
        "from": None,
        "advance": None,
        "size": None,
        "modes": [],
        **fields,
    }


# Season One as stored on 2026-10-07, shortened: the newcomers' final listed first.
SEASON_ONE: dict[str, Any] = {
    "modes": [{"key": "standard", "label": "Standard"}],
    "seeds_per_mode": 3,
    "stages": [
        _stage(
            "newcomers",
            "newcomers",
            label="Newcomers' final",
            size=4,
            modes=["Standard", "Sprint", "Boss Rush"],
        ),
        _stage("group_a", "round", seeds=[1, 4], advance=2),
        _stage("group_b", "round", seeds=[2, 3], advance=2),
        _stage("final", "final", date="2026-11-01", **{"from": ["group_a", "group_b"]}),
    ],
    "showcases": [
        {"key": "showcase", "label": "Ignite Showcase", "date": None, "races": 3, "modes": []}
    ],
    "announced_at": "2026-09-16T08:00:00Z",
    "withdrawn": [],
}


def test_upgrade_wraps_the_bracket_and_turns_the_newcomers_stage_into_a_seeded_final():
    out = migration.wrap_stages_in_brackets(copy.deepcopy(SEASON_ONE))
    assert out is not None
    assert "stages" not in out
    main, newcomers = out["brackets"]
    assert (main["key"], main["label"], main["entry"]) == ("main", "Playoffs", "all")
    assert [s["key"] for s in main["stages"]] == ["group_a", "group_b", "final"]
    assert all("size" not in s for s in main["stages"])
    assert (newcomers["key"], newcomers["label"], newcomers["entry"]) == (
        "newcomers",
        "Newcomers",
        "newcomers",
    )
    (final,) = newcomers["stages"]
    # The key stays, so a race attached to "newcomers:<n>" keeps its slot.
    assert (final["key"], final["label"], final["kind"]) == (
        "newcomers",
        "Newcomers' final",
        "final",
    )
    assert final["seeds"] == [1, 2, 3, 4]
    assert "size" not in final
    assert final["modes"] == ["Standard", "Sprint", "Boss Rush"]
    assert out["showcases"] == SEASON_ONE["showcases"]
    assert out["announced_at"] == SEASON_ONE["announced_at"]


def test_upgrade_leaves_a_document_already_in_brackets_alone():
    out = migration.wrap_stages_in_brackets(copy.deepcopy(SEASON_ONE))
    assert migration.wrap_stages_in_brackets(out) is None


def test_upgrade_turns_an_empty_stage_list_into_no_bracket():
    assert migration.wrap_stages_in_brackets({"modes": [], "stages": []}) == {
        "modes": [],
        "brackets": [],
    }


def test_upgrade_leaves_a_document_without_stages_alone():
    assert migration.wrap_stages_in_brackets({"modes": []}) is None


def test_downgrade_restores_the_flat_list_newcomers_first():
    wrapped = migration.wrap_stages_in_brackets(copy.deepcopy(SEASON_ONE))
    out = migration.unwrap_brackets(wrapped)
    assert out is not None
    assert "brackets" not in out
    assert [s["key"] for s in out["stages"]] == ["newcomers", "group_a", "group_b", "final"]
    newcomers = out["stages"][0]
    assert (newcomers["kind"], newcomers["size"], newcomers["seeds"]) == ("newcomers", 4, None)


def test_downgrade_leaves_a_newcomers_bracket_with_semis_alone():
    wrapped = migration.wrap_stages_in_brackets(copy.deepcopy(SEASON_ONE))
    wrapped["brackets"][1]["stages"] = [
        _stage("newcomers_semi_a", "semi", seeds=[1, 4], advance=2),
        _stage("newcomers_semi_b", "semi", seeds=[2, 3], advance=2),
        _stage("newcomers_final", "final", **{"from": ["newcomers_semi_a", "newcomers_semi_b"]}),
    ]
    assert migration.unwrap_brackets(wrapped) is None


def test_downgrade_leaves_a_document_without_brackets_alone():
    assert migration.unwrap_brackets(copy.deepcopy(SEASON_ONE)) is None


def test_the_migrated_season_one_document_validates():
    from speedfog_racing.schemas import EventConfig

    cfg = EventConfig.model_validate(migration.wrap_stages_in_brackets(copy.deepcopy(SEASON_ONE)))
    assert [b.key for b in cfg.brackets] == ["main", "newcomers"]
    newcomers = cfg.stage("newcomers")
    assert newcomers is not None and newcomers.seeds == [1, 2, 3, 4]
