"""Cheat detection: game debug flags reported by the mod."""

import uuid
from datetime import UTC, datetime
from unittest.mock import MagicMock

import pytest

from speedfog_racing.services.debug_flags import merge_debug_flags
from speedfog_racing.websocket.training.mod import TrainingModHandler

NOW = datetime(2026, 10, 1, 20, 0, tzinfo=UTC)


def test_merge_records_first_observation() -> None:
    merged, added = merge_debug_flags(None, ["one_shot"], igt_ms=83000, node_id="node_a", now=NOW)
    assert added == ["one_shot"]
    assert merged == {
        "one_shot": {"igt_ms": 83000, "node_id": "node_a", "detected_at": NOW.isoformat()}
    }


def test_merge_keeps_first_observation_and_adds_only_new_flags() -> None:
    existing = {"one_shot": {"igt_ms": 1000, "node_id": "start_node", "detected_at": "x"}}
    merged, added = merge_debug_flags(
        existing, ["one_shot", "infinite_stamina"], igt_ms=5000, node_id="node_b", now=NOW
    )
    assert added == ["infinite_stamina"]
    assert merged is not None
    assert merged["one_shot"] == existing["one_shot"]
    assert merged["infinite_stamina"]["igt_ms"] == 5000


def test_merge_with_nothing_new_returns_existing() -> None:
    existing = {"one_shot": {"igt_ms": 1000, "node_id": None, "detected_at": "x"}}
    merged, added = merge_debug_flags(existing, ["one_shot"], igt_ms=9000, node_id=None, now=NOW)
    assert added == []
    assert merged is existing


@pytest.mark.parametrize(
    "reported",
    [None, "one_shot", {"one_shot": True}, [1, 2], ["god_mode"], ["one_shot"] * 65],
)
def test_merge_ignores_malformed_reports(reported: object) -> None:
    assert merge_debug_flags(None, reported, igt_ms=1000, node_id=None, now=NOW) == (None, [])


def test_merge_keeps_known_names_next_to_unknown_ones() -> None:
    # A newer mod may know flags this server does not: keep the known ones.
    merged, added = merge_debug_flags(
        None, ["future_flag", "one_shot"], igt_ms=1000, node_id=None, now=NOW
    )
    assert added == ["one_shot"]
    assert merged is not None and set(merged) == {"one_shot"}


def test_training_sessions_ignore_debug_flags() -> None:
    handler = TrainingModHandler(MagicMock(), uuid.uuid4(), MagicMock())
    assert handler._record_debug_flags(MagicMock(), ["one_shot"], 1000) == []
