"""Tests for countdown feature."""

from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, patch

from speedfog_racing.websocket.race.mod import _is_countdown_active
from speedfog_racing.websocket.schemas import (
    RaceInfo,
    RaceStartMessage,
    RaceStatusChangeMessage,
)


class TestCountdownSchemas:
    """Test countdown_seconds serialization in WS schemas."""

    def test_race_start_message_with_countdown(self):
        msg = RaceStartMessage(countdown_seconds=10)
        data = msg.model_dump()
        assert data["countdown_seconds"] == 10
        assert data["type"] == "race_start"

    def test_race_start_message_default_zero(self):
        msg = RaceStartMessage()
        data = msg.model_dump()
        assert data["countdown_seconds"] == 0

    def test_race_status_change_with_countdown(self):
        msg = RaceStatusChangeMessage(
            status="running",
            started_at="2026-01-01T00:00:00",
            countdown_seconds=10,
        )
        data = msg.model_dump()
        assert data["countdown_seconds"] == 10

    def test_race_status_change_without_countdown(self):
        msg = RaceStatusChangeMessage(status="finished")
        data = msg.model_dump()
        assert data["countdown_seconds"] is None

    def test_race_info_with_countdown(self):
        info = RaceInfo(
            id="test",
            name="Test Race",
            status="running",
            countdown_seconds=10,
        )
        data = info.model_dump()
        assert data["countdown_seconds"] == 10

    def test_race_info_default_zero(self):
        info = RaceInfo(id="test", name="Test Race", status="setup")
        data = info.model_dump()
        assert data["countdown_seconds"] == 0

    def test_race_start_json_includes_countdown(self):
        msg = RaceStartMessage(countdown_seconds=10)
        json_str = msg.model_dump_json()
        assert '"countdown_seconds":10' in json_str

    def test_race_status_change_json_includes_countdown(self):
        msg = RaceStatusChangeMessage(
            status="running",
            started_at="2026-01-01T00:00:00",
            countdown_seconds=10,
        )
        json_str = msg.model_dump_json()
        assert '"countdown_seconds":10' in json_str


class TestIsCountdownActive:
    """Test _is_countdown_active guard function."""

    def _make_race(self, started_at: datetime | None = None) -> MagicMock:
        race = MagicMock()
        race.started_at = started_at
        return race

    @patch("speedfog_racing.websocket.race.mod.settings")
    def test_active_during_countdown_window(self, mock_settings):
        """Race started 2s ago with 10s countdown → active."""
        mock_settings.countdown_seconds = 10
        race = self._make_race(started_at=datetime.now(UTC) - timedelta(seconds=2))
        assert _is_countdown_active(race) is True

    @patch("speedfog_racing.websocket.race.mod.settings")
    def test_inactive_after_countdown_window(self, mock_settings):
        """Race started 15s ago with 10s countdown → inactive."""
        mock_settings.countdown_seconds = 10
        race = self._make_race(started_at=datetime.now(UTC) - timedelta(seconds=15))
        assert _is_countdown_active(race) is False

    @patch("speedfog_racing.websocket.race.mod.settings")
    def test_inactive_when_countdown_zero(self, mock_settings):
        """countdown_seconds=0 → always inactive."""
        mock_settings.countdown_seconds = 0
        race = self._make_race(started_at=datetime.now(UTC) - timedelta(seconds=1))
        assert _is_countdown_active(race) is False

    @patch("speedfog_racing.websocket.race.mod.settings")
    def test_inactive_when_not_started(self, mock_settings):
        """Race with no started_at → inactive."""
        mock_settings.countdown_seconds = 10
        race = self._make_race(started_at=None)
        assert _is_countdown_active(race) is False

    @patch("speedfog_racing.websocket.race.mod.settings")
    def test_handles_naive_started_at(self, mock_settings):
        """Race with naive (no tzinfo) started_at → still works."""
        mock_settings.countdown_seconds = 10
        naive_started = datetime.now(UTC).replace(tzinfo=None) - timedelta(seconds=2)
        race = self._make_race(started_at=naive_started)
        assert _is_countdown_active(race) is True

    @patch("speedfog_racing.websocket.race.mod.settings")
    def test_past_boundary_is_inactive(self, mock_settings):
        """Race started just past countdown_seconds ago → inactive."""
        mock_settings.countdown_seconds = 10
        race = self._make_race(
            started_at=datetime.now(UTC) - timedelta(seconds=10, milliseconds=50)
        )
        assert _is_countdown_active(race) is False
