"""Validation rules of the event config document."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from speedfog_racing.schemas import EventConfig


def _config(**overrides):
    base = {
        "modes": [
            {"key": "standard", "label": "Standard"},
            {"key": "boss_rush", "label": "Boss Rush"},
        ],
        "seeds_per_mode": 2,
        "stages": [
            {
                "key": "semi_a",
                "label": "Semi A",
                "kind": "semi",
                "date": "2026-10-04T19:00:00Z",
                "races": 3,
                "seeds": [1, 4],
            },
            {
                "key": "semi_b",
                "label": "Semi B",
                "kind": "semi",
                "date": "2026-10-11T19:00:00Z",
                "races": 3,
                "seeds": [2, 3],
            },
            {
                "key": "newcomers",
                "label": "Newcomers",
                "kind": "newcomers",
                "date": "2026-10-18T19:00:00Z",
                "races": 2,
                "size": 4,
            },
            {
                "key": "final",
                "label": "Final",
                "kind": "final",
                "date": "2026-10-25T19:00:00Z",
                "races": 3,
                "from": ["semi_a", "semi_b"],
                "advance": 2,
            },
        ],
        "rules": ["One sitting per run."],
    }
    base.update(overrides)
    return base


def test_valid_config_exposes_lookups():
    cfg = EventConfig.model_validate(_config())
    assert cfg.mode_keys() == ["standard", "boss_rush"]
    assert cfg.stage("final") is not None and cfg.stage("final").from_ == ["semi_a", "semi_b"]
    assert cfg.final_stage() is not None and cfg.final_stage().key == "final"
    assert cfg.phase_override is None


def test_duplicate_mode_keys_rejected():
    modes = [{"key": "standard", "label": "A"}, {"key": "standard", "label": "B"}]
    with pytest.raises(ValidationError, match="unique"):
        EventConfig.model_validate(_config(modes=modes))


def test_semi_requires_distinct_seeds():
    stages = _config()["stages"]
    stages[0]["seeds"] = [1, 1]
    with pytest.raises(ValidationError, match="seeds"):
        EventConfig.model_validate(_config(stages=stages))


def test_semi_seeds_must_be_distinct_across_semi_stages():
    stages = _config()["stages"]
    stages[1]["seeds"] = [1, 3]  # seed 1 already used by semi_a
    with pytest.raises(ValidationError, match="distinct across"):
        EventConfig.model_validate(_config(stages=stages))


def test_final_must_reference_semi_stages():
    stages = _config()["stages"]
    stages[3]["from"] = ["semi_a", "newcomers"]
    with pytest.raises(ValidationError, match="from"):
        EventConfig.model_validate(_config(stages=stages))


def test_stage_dates_must_ascend():
    stages = _config()["stages"]
    stages[1]["date"] = "2026-10-03T19:00:00Z"
    with pytest.raises(ValidationError, match="ascending"):
        EventConfig.model_validate(_config(stages=stages))


def test_phase_override_must_be_a_phase():
    with pytest.raises(ValidationError, match="phase_override"):
        EventConfig.model_validate(_config(phase_override="halftime"))


def test_announced_at_must_be_timezone_aware():
    with pytest.raises(ValidationError, match="announced_at"):
        EventConfig.model_validate(_config(announced_at="2026-10-01T10:00:00"))


def test_from_alias_round_trips_through_json_dump():
    cfg = EventConfig.model_validate(_config())
    dumped = cfg.model_dump(mode="json", by_alias=True)
    final_stage_dump = next(s for s in dumped["stages"] if s["key"] == "final")
    assert final_stage_dump["from"] == ["semi_a", "semi_b"]
    assert "from_" not in final_stage_dump

    restored = EventConfig.model_validate(dumped)
    assert restored.stage("final") is not None
    assert restored.stage("final").from_ == cfg.stage("final").from_
