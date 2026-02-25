"""Discord webhook notifications and bot API for race events."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.config import settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from speedfog_racing.models import Participant

logger = logging.getLogger(__name__)

DISCORD_API_BASE = "https://discord.com/api/v10"


async def _discord_api_request(
    method: str,
    path: str,
    *,
    json: dict[str, object] | None = None,
) -> dict[str, object] | None:
    """Make an authenticated Discord API request. Returns response JSON or None on failure."""
    bot_token = settings.discord_bot_token
    if not bot_token:
        return None
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.request(
                method,
                f"{DISCORD_API_BASE}{path}",
                json=json,
                headers={"Authorization": f"Bot {bot_token}"},
            )
            if response.status_code == 429:
                logger.warning("Discord API rate limited: %s", response.headers.get("Retry-After"))
                return None
            if response.status_code == 204:
                return {}
            if response.status_code >= 400:
                logger.warning("Discord API error %d: %s", response.status_code, response.text)
                return None
            return response.json()  # type: ignore[no-any-return]
    except Exception as e:
        logger.warning("Discord API request error: %s", e)
        return None


# ---------------------------------------------------------------------------
# Scheduled events
# ---------------------------------------------------------------------------

EVENT_DURATION = timedelta(hours=3)


async def create_scheduled_event(
    *,
    race_name: str,
    race_id: str,
    scheduled_at: datetime,
) -> str | None:
    """Create a Discord scheduled event for a race. Returns event ID or None."""
    guild_id = settings.discord_guild_id
    if not guild_id:
        return None
    result = await _discord_api_request(
        "POST",
        f"/guilds/{guild_id}/scheduled-events",
        json={
            "name": race_name,
            "entity_type": 3,  # EXTERNAL
            "scheduled_start_time": scheduled_at.isoformat(),
            "scheduled_end_time": (scheduled_at + EVENT_DURATION).isoformat(),
            "entity_metadata": {"location": _race_url(race_id)},
            "privacy_level": 2,  # GUILD_ONLY (required)
        },
    )
    return result["id"] if result and "id" in result else None  # type: ignore[return-value]


async def update_scheduled_event(
    event_id: str,
    *,
    scheduled_at: datetime,
) -> None:
    """Update scheduled time of an existing Discord event."""
    guild_id = settings.discord_guild_id
    if not guild_id:
        return
    await _discord_api_request(
        "PATCH",
        f"/guilds/{guild_id}/scheduled-events/{event_id}",
        json={
            "scheduled_start_time": scheduled_at.isoformat(),
            "scheduled_end_time": (scheduled_at + EVENT_DURATION).isoformat(),
        },
    )


async def delete_scheduled_event(event_id: str) -> None:
    """Delete a Discord scheduled event."""
    guild_id = settings.discord_guild_id
    if not guild_id:
        return
    await _discord_api_request(
        "DELETE",
        f"/guilds/{guild_id}/scheduled-events/{event_id}",
    )


async def set_event_status(event_id: str, status: int) -> None:
    """Update a Discord scheduled event status (2=ACTIVE, 3=COMPLETED)."""
    guild_id = settings.discord_guild_id
    if not guild_id:
        return
    await _discord_api_request(
        "PATCH",
        f"/guilds/{guild_id}/scheduled-events/{event_id}",
        json={"status": status},
    )


# ---------------------------------------------------------------------------
# Role management
# ---------------------------------------------------------------------------


async def assign_runner_role(user_id: str) -> bool:
    """Assign the Runner role to a Discord user."""
    guild_id = settings.discord_guild_id
    role_id = settings.discord_runner_role_id
    if not guild_id or not role_id:
        return False
    result = await _discord_api_request(
        "PUT",
        f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
    )
    return result is not None


async def remove_runner_role(user_id: str) -> bool:
    """Remove the Runner role from a Discord user."""
    guild_id = settings.discord_guild_id
    role_id = settings.discord_runner_role_id
    if not guild_id or not role_id:
        return False
    result = await _discord_api_request(
        "DELETE",
        f"/guilds/{guild_id}/members/{user_id}/roles/{role_id}",
    )
    return result is not None


# ---------------------------------------------------------------------------
# Channel messages
# ---------------------------------------------------------------------------


async def post_runner_message() -> bool:
    """Post the Runner role toggle button message to the configured channel."""
    channel_id = settings.discord_channel_id
    if not channel_id:
        return False
    result = await _discord_api_request(
        "POST",
        f"/channels/{channel_id}/messages",
        json={
            "content": "## Runner Role\nClick below to get notified when races are organized!",
            "components": [
                {
                    "type": 1,  # ACTION_ROW
                    "components": [
                        {
                            "type": 2,  # BUTTON
                            "style": 3,  # SUCCESS (green)
                            "label": "Become a Runner",
                            "custom_id": "become_runner",
                        },
                        {
                            "type": 2,  # BUTTON
                            "style": 4,  # DANGER (red)
                            "label": "Remove Runner",
                            "custom_id": "remove_runner",
                        },
                    ],
                }
            ],
        },
    )
    return result is not None


# ---------------------------------------------------------------------------
# Webhook helpers
# ---------------------------------------------------------------------------


async def _send_webhook(
    embed: dict[str, object],
    *,
    content: str | None = None,
    allowed_mentions: dict[str, object] | None = None,
) -> None:
    """Send an embed to the Discord webhook. No-op if webhook URL is not configured."""
    webhook_url = settings.discord_webhook_url
    if not webhook_url:
        return

    payload: dict[str, object] = {"embeds": [embed]}
    if content:
        payload["content"] = content
    if allowed_mentions:
        payload["allowed_mentions"] = allowed_mentions
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                logger.warning(
                    "Discord webhook rate limited, retry after %s seconds",
                    retry_after,
                )
            elif response.status_code >= 400:
                logger.warning("Discord webhook failed with status %d", response.status_code)
    except Exception as e:
        logger.warning("Discord webhook error: %s", e)


def _race_label_and_color(pool_name: str | None) -> tuple[str, int]:
    """Return (label, color) based on pool type."""
    is_training = pool_name.startswith("training_") if pool_name else False
    label = "Solo" if is_training else "Race"
    color = 0x3B82F6 if is_training else 0xF97316  # blue for solo, orange for race
    return label, color


def _race_url(race_id: str) -> str:
    base_url = settings.base_url.rstrip("/")
    return f"{base_url}/race/{race_id}"


async def notify_race_created(
    *,
    race_name: str,
    race_id: str,
    pool_name: str | None,
    organizer_name: str,
    organizer_avatar_url: str | None,
    scheduled_at: str | None = None,
) -> None:
    """Send Discord notification when a race is created."""
    label, color = _race_label_and_color(pool_name)
    display_pool = format_pool_display_name(pool_name)

    fields: list[dict[str, object]] = [
        {"name": "Pool", "value": display_pool, "inline": True},
        {"name": "Organizer", "value": organizer_name, "inline": True},
    ]
    if scheduled_at:
        fields.append({"name": "Scheduled", "value": scheduled_at, "inline": True})

    embed: dict[str, object] = {
        "title": f"📋 New {label}: {race_name}",
        "url": _race_url(race_id),
        "color": color,
        "fields": fields,
    }
    if organizer_avatar_url:
        embed["thumbnail"] = {"url": organizer_avatar_url}

    role_id = settings.discord_runner_role_id
    content = f"<@&{role_id}>" if role_id else None
    allowed_mentions: dict[str, object] | None = {"roles": [role_id]} if role_id else None
    await _send_webhook(embed, content=content, allowed_mentions=allowed_mentions)


async def notify_race_started(
    *,
    race_name: str,
    race_id: str,
    pool_name: str | None,
    participant_count: int,
    organizer_name: str,
    organizer_avatar_url: str | None,
) -> None:
    """Send Discord notification when a race is started."""
    label, color = _race_label_and_color(pool_name)
    display_pool = format_pool_display_name(pool_name)

    embed: dict[str, object] = {
        "title": f"🏁 {label} Started: {race_name}",
        "url": _race_url(race_id),
        "color": color,
        "fields": [
            {"name": "Pool", "value": display_pool, "inline": True},
            {"name": "Participants", "value": str(participant_count), "inline": True},
            {"name": "Organizer", "value": organizer_name, "inline": True},
        ],
    }
    if organizer_avatar_url:
        embed["thumbnail"] = {"url": organizer_avatar_url}

    await _send_webhook(embed)


def _format_igt(igt_ms: int) -> str:
    """Format IGT milliseconds as H:MM:SS."""
    total_seconds = igt_ms // 1000
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    seconds = total_seconds % 60
    if hours:
        return f"{hours}:{minutes:02d}:{seconds:02d}"
    return f"{minutes}:{seconds:02d}"


def build_podium(participants: Sequence[Participant]) -> list[dict[str, str]]:
    """Build podium data from participants (top 3 finishers by IGT)."""
    from speedfog_racing.models import ParticipantStatus

    finished = [p for p in participants if p.status == ParticipantStatus.FINISHED]
    finished.sort(key=lambda p: p.igt_ms)
    return [
        {
            "name": p.user.twitch_display_name or p.user.twitch_username,
            "igt": _format_igt(p.igt_ms),
        }
        for p in finished[:3]
    ]


async def notify_race_finished(
    *,
    race_name: str,
    race_id: str,
    pool_name: str | None,
    participant_count: int,
    podium: list[dict[str, str]],
) -> None:
    """Send Discord notification when a race finishes.

    podium is a list of {"name": ..., "igt": ...} dicts for top finishers.
    """
    label, _ = _race_label_and_color(pool_name)

    podium_lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, entry in enumerate(podium[:3]):
        medal = medals[i] if i < len(medals) else f"{i + 1}."
        podium_lines.append(f"{medal} **{entry['name']}** — {entry['igt']}")
    podium_text = "\n".join(podium_lines) if podium_lines else "No finishers"

    embed: dict[str, object] = {
        "title": f"🏆 {label} Finished: {race_name}",
        "url": _race_url(race_id),
        "color": 0x22C55E,  # green for finished
        "fields": [
            {"name": "Podium", "value": podium_text, "inline": False},
            {"name": "Participants", "value": str(participant_count), "inline": True},
        ],
    }

    await _send_webhook(embed)
