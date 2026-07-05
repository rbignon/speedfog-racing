"""events.malenia.win calendar API client.

Thin, DB-free wrappers mirroring the scheduled-event helpers in ``discord.py``.
Every call is a no-op when ``settings.malenia_api_token`` is unset.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

from speedfog_racing.config import settings

logger = logging.getLogger(__name__)

# malenia calendar events run 2h (shorter than the 3h Discord scheduled event).
EVENT_DURATION = timedelta(hours=2)

# Added to every event description so calendar visitors who do not know the
# format understand what a SpeedFog race is.
SPEEDFOG_BLURB = (
    "SpeedFog is a competitive Elden Ring speedrunning race: everyone plays the "
    "same randomized fog-gate seed and races to the finish, fastest in-game time wins."
)


async def _malenia_api_request(
    method: str,
    path: str,
    *,
    json: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Make an authenticated malenia API request. Returns JSON, {} on 204, None on failure."""
    token = settings.malenia_api_token
    if not token:
        return None
    base = settings.malenia_api_base.rstrip("/")
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method,
                f"{base}{path}",
                json=json,
                headers={"Authorization": f"Bearer {token}"},
            )
            if response.status_code == 429:
                logger.warning("malenia API rate limited: %s", response.headers.get("Retry-After"))
                return None
            if response.status_code == 204:
                return {}
            if response.status_code >= 400:
                logger.warning("malenia API error %d: %s", response.status_code, response.text)
                return None
            return response.json()  # type: ignore[no-any-return]
    except Exception as e:
        logger.warning("malenia API request error: %s", e)
        return None


def _event_url(race_id: str) -> str:
    return f"{settings.base_url.rstrip('/')}/race/{race_id}"


def _image_url(race_id: str) -> str:
    return f"{settings.base_url.rstrip('/')}/api/og/race/{race_id}.png"


def _title(race_name: str) -> str:
    """Prefix the race name so it stands out among other event types on the calendar."""
    return f"Speedfog - {race_name}"


def _description(mode_display: str, custom_rules: str | None) -> str:
    """Build the event description: mode, a blurb about SpeedFog, then optional rules."""
    text = f"Mode: {mode_display}\n\n{SPEEDFOG_BLURB}"
    if custom_rules:
        text = f"{text}\n\n{custom_rules}"
    return text


async def create_calendar_event(
    *,
    race_name: str,
    race_id: str,
    organizer_login: str,
    scheduled_at: datetime,
    mode_display: str,
    custom_rules: str | None,
) -> str | None:
    """Create a malenia calendar event for a race. Returns event ID or None."""
    result = await _malenia_api_request(
        "POST",
        "/events",
        json={
            "title": _title(race_name),
            "starts_at": scheduled_at.isoformat(),
            "ends_at": (scheduled_at + EVENT_DURATION).isoformat(),
            "event_url": _event_url(race_id),
            "image_url": _image_url(race_id),
            "description": _description(mode_display, custom_rules),
            "organizer_login": organizer_login,
            "allow_self_join": False,
            "all_day": False,
        },
    )
    return result["id"] if result and "id" in result else None  # type: ignore[return-value]


async def update_calendar_event(
    event_id: str,
    *,
    scheduled_at: datetime | None = None,
    race_name: str | None = None,
    mode_display: str | None = None,
    custom_rules: str | None = None,
) -> None:
    """Patch a malenia event, sending only the provided fields.

    ``description`` is rebuilt (and patched) whenever ``mode_display`` is given,
    which also covers clearing ``custom_rules`` (passed as None alongside it).
    """
    body: dict[str, object] = {}
    if scheduled_at is not None:
        body["starts_at"] = scheduled_at.isoformat()
        body["ends_at"] = (scheduled_at + EVENT_DURATION).isoformat()
    if race_name is not None:
        body["title"] = _title(race_name)
    if mode_display is not None:
        body["description"] = _description(mode_display, custom_rules)
    if not body:
        return
    await _malenia_api_request("PATCH", f"/events/{event_id}", json=body)


async def delete_calendar_event(event_id: str) -> None:
    """Delete a malenia calendar event."""
    await _malenia_api_request("DELETE", f"/events/{event_id}")


async def add_event_participant(event_id: str, login: str) -> None:
    """Add a participant to a malenia event by Twitch login (auto-created if unknown)."""
    await _malenia_api_request("POST", f"/events/{event_id}/participants", json={"login": login})


async def remove_event_participant_by_login(event_id: str, login: str) -> None:
    """Remove the event participant with the given Twitch login.

    malenia's delete endpoint needs the participant's malenia UUID, which we do
    not store, so we fetch the event and match on ``twitch_username``.
    """
    detail = await _malenia_api_request("GET", f"/events/{event_id}")
    if not detail:
        return
    participants = detail.get("participants")
    if not isinstance(participants, list):
        return
    target = login.lower()
    for participant in participants:
        if not isinstance(participant, dict):
            continue
        if str(participant.get("twitch_username", "")).lower() == target:
            user_id = participant.get("id")
            if user_id:
                await _malenia_api_request("DELETE", f"/events/{event_id}/participants/{user_id}")
            return
