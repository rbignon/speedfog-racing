"""Tests for countdown feature."""

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
