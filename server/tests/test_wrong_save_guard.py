"""Wrong-save guard: IGT plausibility and reload handling.

Regressions are always plausible (backup restores are legitimate); a
forward jump is implausible when it outruns wall-clock time since the
last accepted report (in-game time cannot advance faster than real time).
"""

from datetime import UTC, datetime, timedelta

from speedfog_racing.websocket.handler import (
    WRONG_SAVE_FORWARD_SLACK_MS,
    is_igt_plausible,
)

NOW = datetime(2026, 7, 25, 12, 0, 0, tzinfo=UTC)


def test_any_regression_is_plausible() -> None:
    """Backup restores can roll the IGT back by any amount."""
    ref = NOW - timedelta(seconds=5)
    assert is_igt_plausible(3_600_000, ref, 3_599_000, NOW)  # small (quit-out)
    assert is_igt_plausible(3_600_000, ref, 600_000, NOW)  # huge (restore)
    assert is_igt_plausible(3_600_000, ref, 3_600_000, NOW)  # equal


def test_forward_within_wall_clock_is_plausible() -> None:
    """IGT advancing no faster than real time is fine, at any gap size."""
    # 30 minutes of disconnection, 29 minutes of IGT gained: plausible.
    ref = NOW - timedelta(minutes=30)
    assert is_igt_plausible(600_000, ref, 600_000 + 29 * 60_000, NOW)
    # Exactly wall + slack: still plausible (boundary).
    ref = NOW - timedelta(seconds=100)
    assert is_igt_plausible(0, ref, 100_000 + WRONG_SAVE_FORWARD_SLACK_MS, NOW)


def test_forward_beyond_wall_clock_is_implausible() -> None:
    """In-game time cannot outrun real time: wrong save."""
    ref = NOW - timedelta(seconds=10)
    # +2 hours of IGT in 10 wall seconds.
    assert not is_igt_plausible(600_000, ref, 600_000 + 7_200_000, NOW)
    # Just past the slack boundary.
    assert not is_igt_plausible(0, ref, 10_000 + WRONG_SAVE_FORWARD_SLACK_MS + 1, NOW)


def test_no_wall_reference_disables_forward_check() -> None:
    """Training (no last_igt_change_at) never rejects."""
    assert is_igt_plausible(600_000, None, 99_999_999, NOW)


def test_naive_wall_reference_is_normalized() -> None:
    """SQLite round-trips DateTime(timezone=True) as naive; the check must
    not raise and must judge identically to the aware equivalent."""
    naive_ref = (NOW - timedelta(seconds=10)).replace(tzinfo=None)
    assert not is_igt_plausible(600_000, naive_ref, 600_000 + 7_200_000, NOW)
    assert is_igt_plausible(600_000, naive_ref, 599_000, NOW)
