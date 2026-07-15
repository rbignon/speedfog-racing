"""Tests for the events.malenia.win API client."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch

import pytest

from speedfog_racing import malenia
from speedfog_racing.config import settings


@pytest.mark.asyncio
async def test_create_calendar_event_builds_payload(monkeypatch):
    monkeypatch.setattr(settings, "base_url", "https://example.test")
    scheduled = datetime(2026, 7, 3, 18, 0, tzinfo=UTC)

    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        mock_req.return_value = {"id": "evt-1"}
        result = await malenia.create_calendar_event(
            race_name="Fog Race",
            race_id="abc",
            organizer_login="runnerlogin",
            scheduled_at=scheduled,
            mode_display="Standard",
            custom_rules="No summons",
        )

    assert result == "evt-1"
    method, path = mock_req.call_args[0]
    body = mock_req.call_args[1]["json"]
    assert (method, path) == ("POST", "/events")
    assert body["title"] == "Speedfog - Fog Race"
    assert body["starts_at"] == scheduled.isoformat()
    assert body["ends_at"] == (scheduled + timedelta(hours=1)).isoformat()
    assert body["event_url"] == "https://example.test/race/abc"
    assert body["image_url"] == "https://example.test/api/og/race/abc.png"
    assert body["organizer_login"] == "runnerlogin"
    assert body["allow_self_join"] is False
    assert body["all_day"] is False
    assert "No summons" in body["description"]
    assert "Standard" in body["description"]
    assert "SpeedFog" in body["description"]


@pytest.mark.asyncio
async def test_create_calendar_event_no_token_short_circuits(monkeypatch):
    monkeypatch.setattr(settings, "malenia_api_token", None)
    with patch("speedfog_racing.malenia.httpx.AsyncClient") as mock_client:
        result = await malenia.create_calendar_event(
            race_name="Fog Race",
            race_id="abc",
            organizer_login="x",
            scheduled_at=datetime(2026, 7, 3, 18, 0, tzinfo=UTC),
            mode_display="Standard",
            custom_rules=None,
        )
    assert result is None
    mock_client.assert_not_called()


@pytest.mark.asyncio
async def test_update_calendar_event_sends_only_provided_fields():
    scheduled = datetime(2026, 7, 3, 18, 0, tzinfo=UTC)
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        await malenia.update_calendar_event("evt-1", scheduled_at=scheduled)
        time_body = mock_req.call_args[1]["json"]
        assert set(time_body) == {"starts_at", "ends_at"}

        await malenia.update_calendar_event(
            "evt-1", race_name="New", mode_display="Standard", custom_rules="rules"
        )
        meta_body = mock_req.call_args[1]["json"]
        assert set(meta_body) == {"title", "description"}
        assert meta_body["title"] == "Speedfog - New"


@pytest.mark.asyncio
async def test_update_calendar_event_noop_when_nothing_changed():
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        await malenia.update_calendar_event("evt-1")
    mock_req.assert_not_called()


@pytest.mark.asyncio
async def test_add_event_participant_posts_login():
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        await malenia.add_event_participant("evt-1", "runner")
    mock_req.assert_awaited_once_with(
        "POST", "/events/evt-1/participants", json={"login": "runner"}
    )


@pytest.mark.asyncio
async def test_remove_event_participant_by_login_deletes_matching_id():
    detail = {
        "participants": [
            {"id": "uuid-aaa", "twitch_username": "Someone"},
            {"id": "uuid-bbb", "twitch_username": "TargetUser"},
        ]
    }
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = [detail, {}]
        await malenia.remove_event_participant_by_login("evt-1", "targetuser")
    assert mock_req.call_count == 2
    assert mock_req.call_args_list[0].args == ("GET", "/events/evt-1")
    assert mock_req.call_args_list[1].args == ("DELETE", "/events/evt-1/participants/uuid-bbb")


@pytest.mark.asyncio
async def test_remove_event_participant_by_login_no_match_skips_delete():
    detail = {"participants": [{"id": "uuid-aaa", "twitch_username": "Someone"}]}
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = [detail]
        await malenia.remove_event_participant_by_login("evt-1", "ghost")
    assert mock_req.call_count == 1


@pytest.mark.asyncio
async def test_remove_event_participant_by_login_empty_response_is_noop():
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = [{}]
        await malenia.remove_event_participant_by_login("evt-1", "anyone")
    assert mock_req.call_count == 1


@pytest.mark.asyncio
async def test_remove_event_participant_by_login_participants_not_a_list():
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = [{"participants": "oops"}]
        await malenia.remove_event_participant_by_login("evt-1", "anyone")
    assert mock_req.call_count == 1


@pytest.mark.asyncio
async def test_remove_event_participant_by_login_match_without_id_skips_delete():
    detail = {"participants": [{"twitch_username": "TargetUser"}]}
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = [detail]
        await malenia.remove_event_participant_by_login("evt-1", "targetuser")
    assert mock_req.call_count == 1


@pytest.mark.asyncio
async def test_remove_event_participant_by_login_skips_non_dict_items():
    detail = {"participants": ["junk", {"id": "uuid-ccc", "twitch_username": "Target"}]}
    with patch.object(malenia, "_malenia_api_request", new_callable=AsyncMock) as mock_req:
        mock_req.side_effect = [detail, {}]
        await malenia.remove_event_participant_by_login("evt-1", "target")
    assert mock_req.call_count == 2
    assert mock_req.call_args_list[1].args == ("DELETE", "/events/evt-1/participants/uuid-ccc")
