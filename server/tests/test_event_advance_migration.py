"""The data migration that moves ``advance`` onto the stages sending runners on."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
from pydantic import ValidationError

from speedfog_racing.schemas import EventConfig

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "4f7c2a9d1e6b_move_event_advance_onto_source_stages.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("advance_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load()


def _stage(key: str, kind: str, date: str, **fields: Any) -> dict[str, Any]:
    # Stored documents carry every field, null when unset (model_dump output).
    return {
        "key": key,
        "label": key.replace("_", " ").title(),
        "kind": kind,
        "date": date,
        "races": 3,
        "seeds": None,
        "from": None,
        "advance": None,
        "size": None,
        "modes": [],
        **fields,
    }


# The production document's shape: newcomers first, the final carrying advance.
PRODUCTION = {
    "modes": [{"key": "standard", "label": "Standard"}],
    "seeds_per_mode": 3,
    "stages": [
        _stage("newcomers", "newcomers", "2026-10-09T19:00:00Z", size=4),
        _stage("semi_a", "semi", "2026-10-11T19:00:00Z", seeds=[1, 4, 5, 8]),
        _stage("semi_b", "semi", "2026-10-18T19:00:00Z", seeds=[2, 3, 6, 7]),
        _stage(
            "final",
            "final",
            "2026-10-25T19:00:00Z",
            **{"from": ["semi_a", "semi_b"]},
            advance=2,
        ),
    ],
    "rules": [],
    "playoff_rules": [],
    "facts": None,
    "phase_override": None,
    "announced_at": "2026-09-16T08:00:00Z",
}


def test_the_production_document_no_longer_validates_as_stored():
    with pytest.raises(ValidationError):
        EventConfig.model_validate(PRODUCTION)


def test_upgrade_moves_the_final_advance_onto_the_semis():
    moved = migration.move_advance_to_sources(PRODUCTION)
    assert moved is not None
    by_key = {s["key"]: s for s in moved["stages"]}
    assert by_key["semi_a"]["advance"] == 2 and by_key["semi_b"]["advance"] == 2
    assert by_key["final"].get("advance") is None
    cfg = EventConfig.model_validate(moved)
    final = cfg.stage("final")
    assert final is not None and cfg.field_size(final) == 4
    # The input document is left as it was.
    assert PRODUCTION["stages"][3]["advance"] == 2


def test_upgrade_changes_nothing_on_a_second_run_or_a_three_round_document():
    moved = migration.move_advance_to_sources(PRODUCTION)
    assert moved is not None
    assert migration.move_advance_to_sources(moved) is None
    three_rounds = {
        **PRODUCTION,
        "stages": [
            _stage("quarter_a", "quarter", "2026-10-09T19:00:00Z", seeds=[1, 4], advance=1),
            _stage("quarter_b", "quarter", "2026-10-10T19:00:00Z", seeds=[2, 3], advance=1),
            _stage(
                "semi_a",
                "semi",
                "2026-10-11T19:00:00Z",
                **{"from": ["quarter_a", "quarter_b"]},
                advance=2,
            ),
            _stage("final", "final", "2026-10-25T19:00:00Z", **{"from": ["semi_a"]}),
        ],
    }
    EventConfig.model_validate(three_rounds)
    assert migration.move_advance_to_sources(three_rounds) is None
    assert migration.move_advance_to_sources({"modes": []}) is None


def test_downgrade_restores_the_old_shape_and_leaves_what_it_cannot_express():
    moved = migration.move_advance_to_sources(PRODUCTION)
    assert moved is not None
    restored = migration.move_advance_to_takers(moved)
    assert restored is not None
    by_key = {s["key"]: s for s in restored["stages"]}
    assert by_key["final"]["advance"] == 2
    assert by_key["semi_a"].get("advance") is None and by_key["semi_b"].get("advance") is None
    # A semi fed by quarters has no place in the old model: left untouched.
    three_rounds = {
        **PRODUCTION,
        "stages": [
            _stage("quarter_a", "quarter", "2026-10-09T19:00:00Z", seeds=[1, 2], advance=1),
            _stage("semi_a", "semi", "2026-10-11T19:00:00Z", **{"from": ["quarter_a"]}, advance=1),
            _stage("final", "final", "2026-10-25T19:00:00Z", **{"from": ["semi_a"]}),
        ],
    }
    assert migration.move_advance_to_takers(three_rounds) is None
