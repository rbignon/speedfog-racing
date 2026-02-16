"""Discord webhook notifications for race events."""

import logging

import httpx

from speedfog_racing.config import settings

logger = logging.getLogger(__name__)


async def notify_race_started(
    *,
    race_name: str,
    race_id: str,
    pool_name: str | None,
    participant_count: int,
    organizer_name: str,
    organizer_avatar_url: str | None,
) -> None:
    """Send Discord notification when a race or training is started."""
    webhook_url = settings.discord_webhook_url
    if not webhook_url:
        return

    base_url = settings.base_url.rstrip("/")
    race_url = f"{base_url}/race/{race_id}"

    is_training = pool_name.startswith("training_") if pool_name else False
    label = "Training" if is_training else "Race"
    color = 0x3B82F6 if is_training else 0xF97316  # blue for training, orange for race

    # Clean up pool display name: "training_sprint" -> "Sprint", "standard" -> "Standard"
    display_pool = pool_name or "unknown"
    if display_pool.startswith("training_"):
        display_pool = display_pool.removeprefix("training_")
    display_pool = display_pool.replace("_", " ").title()

    embed: dict[str, object] = {
        "title": f"{label}: {race_name}",
        "url": race_url,
        "color": color,
        "fields": [
            {"name": "Pool", "value": display_pool, "inline": True},
            {"name": "Participants", "value": str(participant_count), "inline": True},
            {"name": "Organizer", "value": organizer_name, "inline": True},
        ],
    }
    if organizer_avatar_url:
        embed["thumbnail"] = {"url": organizer_avatar_url}

    payload = {"embeds": [embed]}

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
