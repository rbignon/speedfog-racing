"""Discord webhook notifications and bot API for race events."""

from __future__ import annotations

import asyncio
import logging
import re
import time
import uuid
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

import httpx

from speedfog_racing.api.helpers import format_pool_display_name
from speedfog_racing.config import settings
from speedfog_racing.services.twitch_live import twitch_live_service

if TYPE_CHECKING:
    from collections.abc import Sequence

    from speedfog_racing.models import Participant, Pool, Race, User

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
            "content": "## Runner Role\nClick below to get notified when races are organized",
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


_DISCORD_MD_RE = re.compile(r"([*_~|>`\[\]()])")


def _escape_discord_md(text: str) -> str:
    """Escape Discord markdown special characters in user-provided text."""
    return _DISCORD_MD_RE.sub(r"\\\1", text)


def _race_label_and_color(pool: Pool | None) -> tuple[str, int]:
    """Return (label, color) based on pool type."""
    pool_name = pool.name if pool else None
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
    pool: Pool | None,
    organizer_name: str,
    organizer_avatar_url: str | None,
    scheduled_at: str | None = None,
) -> None:
    """Send Discord notification when a race is created."""
    label, color = _race_label_and_color(pool)
    display_pool = format_pool_display_name(pool)

    safe_name = _escape_discord_md(race_name)
    safe_organizer = _escape_discord_md(organizer_name)

    fields: list[dict[str, object]] = [
        {"name": "Mode", "value": display_pool, "inline": True},
        {"name": "Organizer", "value": safe_organizer, "inline": True},
    ]
    if scheduled_at:
        fields.append({"name": "Scheduled", "value": scheduled_at, "inline": True})

    embed: dict[str, object] = {
        "title": f"📋 New {label}: {safe_name}",
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
    pool: Pool | None,
    participant_count: int,
    organizer_name: str,
    organizer_avatar_url: str | None,
    registration_closes_at: datetime | None = None,
) -> None:
    """Send Discord notification when a race is started."""
    label, color = _race_label_and_color(pool)
    display_pool = format_pool_display_name(pool)
    safe_name = _escape_discord_md(race_name)
    safe_organizer = _escape_discord_md(organizer_name)

    fields: list[dict[str, object]] = [
        {"name": "Mode", "value": display_pool, "inline": True},
        {"name": "Participants", "value": str(participant_count), "inline": True},
        {"name": "Organizer", "value": safe_organizer, "inline": True},
    ]
    if registration_closes_at is not None:
        ts = int(registration_closes_at.timestamp())
        fields.append(
            {
                "name": "Late registration",
                "value": f"Open until <t:{ts}:t> (<t:{ts}:R>)",
                "inline": False,
            }
        )

    embed: dict[str, object] = {
        "title": f"🏁 {label} Started: {safe_name}",
        "url": _race_url(race_id),
        "color": color,
        "fields": fields,
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
    pool: Pool | None,
    participant_count: int,
    podium: list[dict[str, str]],
) -> None:
    """Send Discord notification when a race finishes.

    podium is a list of {"name": ..., "igt": ...} dicts for top finishers.
    """
    label, _ = _race_label_and_color(pool)
    safe_name = _escape_discord_md(race_name)

    podium_lines = []
    medals = ["🥇", "🥈", "🥉"]
    for i, entry in enumerate(podium[:3]):
        medal = medals[i] if i < len(medals) else f"{i + 1}."
        safe_player = _escape_discord_md(entry["name"])
        podium_lines.append(f"{medal} **{safe_player}** - {entry['igt']}")
    podium_text = "\n".join(podium_lines) if podium_lines else "No finishers"

    embed: dict[str, object] = {
        "title": f"🏆 {label} Finished: {safe_name}",
        "url": _race_url(race_id),
        "color": 0x22C55E,  # green for finished
        "fields": [
            {"name": "Podium", "value": podium_text, "inline": False},
            {"name": "Participants", "value": str(participant_count), "inline": True},
        ],
    }

    await _send_webhook(embed)


async def notify_daily_seed_created(race: Race, previous_race: Race | None) -> None:
    """Announce the new Daily Seed and (optionally) yesterday's podium.

    The link points at the dedicated daily landing page, not the regular
    race route, so the message ages gracefully once the day rolls over.
    """
    from speedfog_racing.models import ParticipantStatus  # avoid circular import at module load
    from speedfog_racing.services.daily_streak_service import qualifies_for_streak

    pool = race.seed.pool if race.seed else None
    pool_display = format_pool_display_name(pool)
    base_url = settings.base_url.rstrip("/")
    daily_url = f"{base_url}/daily"

    title_date = race.daily_date.strftime("%B %-d") if race.daily_date is not None else race.name
    title = f"🌅 Daily Seed - {title_date}"

    closes_at = race.started_at + timedelta(hours=24) if race.started_at else None
    closes_text = f"<t:{int(closes_at.timestamp())}:R>" if closes_at else "in 24 hours"

    description_lines = [
        f"Today's mode: **{_escape_discord_md(pool_display)}**",
        f"Closes {closes_text}.",
        f"[Play now]({daily_url})",
    ]

    if race.deathless:
        description_lines.insert(1, "💀 **Deathless**: dying once eliminates you.")

    if previous_race is not None:
        finishers = sorted(
            [p for p in previous_race.participants if p.status == ParticipantStatus.FINISHED],
            key=lambda p: p.igt_ms,
        )
        if finishers:
            podium_lines = []
            medals = ["🥇", "🥈", "🥉"]
            for i, p in enumerate(finishers[:3]):
                medal = medals[i] if i < len(medals) else f"{i + 1}."
                safe_player = _escape_discord_md(
                    p.user.twitch_display_name or p.user.twitch_username
                )
                podium_lines.append(f"{medal} **{safe_player}** - {_format_igt(p.igt_ms)}")
            qualified_count = sum(
                1 for p in previous_race.participants if qualifies_for_streak(p.zone_history)
            )
            description_lines.append("")
            description_lines.append("**Yesterday's podium**")
            description_lines.extend(podium_lines)
            description_lines.append(f"_{qualified_count} players._")

    embed: dict[str, object] = {
        "title": title,
        "url": daily_url,
        "color": 0x22C55E,
        "description": "\n".join(description_lines),
    }
    await _send_webhook(embed, allowed_mentions={"parse": []})


def fire_race_finished_notifications(race: Race, *, forced: bool = False) -> None:
    """Fire-and-forget Discord notifications for a finished race.

    Creates background tasks for the webhook notification (public races)
    and the scheduled event status update (if a Discord event exists).

    The `forced` flag is plumbed through so future logic (daily seed Discord
    copy, etc.) can differentiate between auto-finish and hard-close paths;
    current implementation ignores it.
    """
    del forced  # currently unused, reserved for future copy differentiation
    # Daily Seeds already announced themselves at creation (notify_daily_seed_created
    # carries yesterday's podium). Posting the regular finished-race embed again at
    # T+24h would double the channel traffic, so we suppress it here.
    if race.is_public and race.daily_date is None:
        task = asyncio.create_task(
            notify_race_finished(
                race_name=race.name,
                race_id=str(race.id),
                pool=race.seed.pool if race.seed else None,
                participant_count=len(race.participants),
                podium=build_podium(race.participants),
            )
        )
        task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)

    if race.discord_event_id:
        ev_task = asyncio.create_task(set_event_status(race.discord_event_id, 3))
        ev_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)


# ---------------------------------------------------------------------------
# Training live notifications
# ---------------------------------------------------------------------------

TRAINING_NOTIF_COOLDOWN_SECONDS = 1800  # 30 minutes

# {user_id: monotonic timestamp of last notification}
_training_notif_cooldowns: dict[uuid.UUID, float] = {}


async def _send_training_webhook(embed: dict[str, object]) -> None:
    """Send an embed to the training Discord webhook. No-op if not configured."""
    webhook_url = settings.discord_training_webhook_url
    if not webhook_url:
        return

    payload: dict[str, object] = {"embeds": [embed]}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                logger.warning(
                    "Discord training webhook rate limited, retry after %s seconds",
                    retry_after,
                )
            elif response.status_code >= 400:
                logger.warning(
                    "Discord training webhook failed with status %d", response.status_code
                )
    except Exception as e:
        logger.warning("Discord training webhook error: %s", e)


def _check_training_cooldown(user_id: uuid.UUID) -> bool:
    """Check if a training notification can be sent for this user.

    Returns True if allowed (no active cooldown). Prunes expired entries.
    """
    now = time.monotonic()
    # Prune expired entries
    expired = [
        uid
        for uid, ts in _training_notif_cooldowns.items()
        if now - ts >= TRAINING_NOTIF_COOLDOWN_SECONDS
    ]
    for uid in expired:
        del _training_notif_cooldowns[uid]

    last = _training_notif_cooldowns.get(user_id)
    if last is not None and now - last < TRAINING_NOTIF_COOLDOWN_SECONDS:
        logger.debug("Training notification cooldown active for user %d", user_id)
        return False
    return True


async def send_training_live_notification(
    *,
    session_id: str,
    user: User,
    pool: Pool | None,
) -> None:
    """Send Discord notification for a live training session.

    Checks webhook config, cooldown, and Twitch live status before sending.
    Designed to be called via fire-and-forget asyncio.create_task().
    """
    if not settings.discord_training_webhook_url:
        return

    if not _check_training_cooldown(user.id):
        return

    # Direct Twitch API check (not from polling cache which only covers races)
    live_usernames = await twitch_live_service.check_live_status([user.twitch_username])
    if user.twitch_username.lower() not in live_usernames:
        return

    display_name = _escape_discord_md(user.twitch_display_name or user.twitch_username)
    display_pool = format_pool_display_name(pool)
    stream_url = f"https://twitch.tv/{user.twitch_username}"

    embed: dict[str, object] = {
        "title": f"🎮 {display_name} is streaming a solo SpeedFog run",
        "url": f"[twitch.tv/{user.twitch_username}]({stream_url})",
        "color": 0x3B82F6,  # blue (training/solo)
        "fields": [
            {"name": "Mode", "value": display_pool, "inline": True},
        ],
    }
    if user.twitch_avatar_url:
        embed["thumbnail"] = {"url": user.twitch_avatar_url}

    await _send_training_webhook(embed)

    # Record cooldown on success
    _training_notif_cooldowns[user.id] = time.monotonic()
