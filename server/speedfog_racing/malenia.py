"""events.malenia.win calendar API client.

Thin, DB-free wrappers mirroring the scheduled-event helpers in ``discord.py``.
Every call is a no-op when ``settings.malenia_api_token`` is unset.
"""

from __future__ import annotations

import logging
from datetime import datetime

import httpx

from speedfog_racing.config import settings
from speedfog_racing.discord import EVENT_DURATION

logger = logging.getLogger(__name__)


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


def _description(mode_display: str, custom_rules: str | None) -> str:
    """Build the event description from the mode and optional custom rules."""
    text = f"Mode: {mode_display}"
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
            "title": race_name,
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
        body["title"] = race_name
    if mode_display is not None:
        body["description"] = _description(mode_display, custom_rules)
    if not body:
        return
    await _malenia_api_request("PATCH", f"/events/{event_id}", json=body)


async def delete_calendar_event(event_id: str) -> None:
    """Delete a malenia calendar event."""
    await _malenia_api_request("DELETE", f"/events/{event_id}")
