"""Tests for countdown feature."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock

from speedfog_racing.websocket.race.mod import _is_countdown_active


class TestIsCountdownActive:
    """Test _is_countdown_active guard function.

    With started_at representing the effective gameplay start (server
    shifts it by countdown_seconds at race launch), the countdown window
    is simply ``now < started_at``.
    """

    def _make_race(self, started_at: datetime | None = None) -> MagicMock:
        race = MagicMock()
        race.started_at = started_at
        return race

    def test_active_when_started_at_is_future(self):
        """started_at 5s in the future → countdown active."""
        race = self._make_race(started_at=datetime.now(UTC) + timedelta(seconds=5))
        assert _is_countdown_active(race) is True

    def test_inactive_when_started_at_passed(self):
        """started_at 5s in the past → countdown over."""
        race = self._make_race(started_at=datetime.now(UTC) - timedelta(seconds=5))
        assert _is_countdown_active(race) is False

    def test_inactive_when_not_started(self):
        """Race with no started_at → inactive."""
        race = self._make_race(started_at=None)
        assert _is_countdown_active(race) is False

    def test_handles_naive_started_at(self):
        """Race with naive (no tzinfo) started_at in future → active."""
        naive_started = datetime.now(UTC).replace(tzinfo=None) + timedelta(seconds=5)
        race = self._make_race(started_at=naive_started)
        assert _is_countdown_active(race) is True
