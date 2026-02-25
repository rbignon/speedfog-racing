"""Discord webhook notifications for race events."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import httpx

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.config import settings

if TYPE_CHECKING:
    from collections.abc import Sequence

    from speedfog_racing.models import Participant

logger = logging.getLogger(__name__)


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

    await _send_webhook(embed)


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
