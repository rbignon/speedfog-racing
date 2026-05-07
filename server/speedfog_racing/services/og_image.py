"""OG image rendering pipeline: Jinja SVG templates → PNG bytes."""

from __future__ import annotations

import asyncio
import base64
import datetime as dt
import hashlib
import logging
from collections.abc import Awaitable, Callable
from datetime import UTC
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import resvg_py
from jinja2 import Environment, FileSystemLoader, select_autoescape

from speedfog_racing.models import ParticipantStatus, Race, RaceStatus

logger = logging.getLogger(__name__)

_TEMPLATES_DIR = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(_TEMPLATES_DIR),
    autoescape=select_autoescape(["svg", "xml"]),
)

_TEMPLATE_BY_STATUS = {
    "setup": "og/setup.svg.j2",
    "running": "og/running.svg.j2",
    "finished": "og/finished.svg.j2",
    "daily": "og/daily.svg.j2",
}


def render_svg(status: str, ctx: dict[str, Any]) -> str:
    """Render the OG SVG for a given race status."""
    name = _TEMPLATE_BY_STATUS[status]
    template = _env.get_template(name)
    return template.render(**ctx)


def rasterize_svg(svg: str) -> bytes:
    """Rasterize an SVG string to PNG bytes at the SVG's intrinsic size."""
    return bytes(resvg_py.svg_to_bytes(svg_string=svg))


_MAX_RACE_NAME = 36
_MAX_AVATARS = 6


STATUS_LABEL = {
    RaceStatus.SETUP: "Upcoming",
    RaceStatus.RUNNING: "Live",
    RaceStatus.FINISHED: "Finished",
}

ACCENT_COLOR = {
    RaceStatus.SETUP: "#3b82f6",
    RaceStatus.RUNNING: "#ef4444",
    RaceStatus.FINISHED: "#10b981",
}

assert ACCENT_COLOR.keys() == STATUS_LABEL.keys(), (
    "ACCENT_COLOR and STATUS_LABEL must cover the same RaceStatus values"
)


def _truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def format_pool(race: Race) -> str:
    if race.seed is None:
        return "Unknown pool"
    pool = race.seed.pool
    name = pool.config.get("name") if pool.config else None
    if name:
        return str(name)
    return pool.name.replace("_", " ").title()


def _format_scheduled(scheduled_at: Any, tz_name: str | None) -> str | None:
    if scheduled_at is None:
        return None
    tz: Any = UTC
    if tz_name:
        try:
            tz = ZoneInfo(tz_name)
        except ZoneInfoNotFoundError:
            logger.warning("invalid organizer timezone %r, falling back to UTC", tz_name)
    local = scheduled_at.astimezone(tz)
    offset = local.utcoffset() or dt.timedelta(0)
    total_minutes = int(offset.total_seconds() // 60)
    sign = "+" if total_minutes >= 0 else "-"
    hours, minutes = divmod(abs(total_minutes), 60)
    if minutes:
        suffix = f"UTC{sign}{hours}:{minutes:02d}"
    elif total_minutes == 0:
        suffix = "UTC"
    else:
        suffix = f"UTC{sign}{hours}"
    return str(local.strftime("%b %d, %H:%M")) + " " + suffix


def _b64(avatar_bytes: bytes) -> str:
    return "data:image/png;base64," + base64.b64encode(avatar_bytes).decode("ascii")


def _previews(race: Race) -> tuple[list[Any], int, Any]:
    """Return (avatar_previews, overflow_count, winner_participant_or_None)."""
    if race.status == RaceStatus.FINISHED:
        finished = sorted(
            (p for p in race.participants if p.status == ParticipantStatus.FINISHED),
            key=lambda p: p.igt_ms,
        )
        non_finished = [p for p in race.participants if p.status != ParticipantStatus.FINISHED]
        ordered = finished + non_finished
        winner_p = finished[0] if finished else None
    else:
        ordered = list(race.participants)
        winner_p = None

    head = ordered[:_MAX_AVATARS]
    overflow = max(0, len(ordered) - _MAX_AVATARS)
    return head, overflow, winner_p


def _participant_count_label(race: Race) -> str:
    n = len(race.participants)
    if race.status == RaceStatus.SETUP and race.max_participants is not None:
        body = f"{n}/{race.max_participants} player"
    else:
        body = f"{n} player"
    if n != 1:
        body += "s"
    return body


AvatarLookup = Callable[[str | None], bytes] | Callable[[str | None], Awaitable[bytes]]


async def _resolve(lookup: AvatarLookup, url: str | None) -> bytes:
    result = lookup(url)
    if hasattr(result, "__await__"):
        return await result
    return result


async def build_context(race: Race, *, avatar_lookup: AvatarLookup) -> dict[str, Any]:
    head, overflow, winner_p = _previews(race)
    participants = []
    for p in head:
        avatar_bytes = await _resolve(avatar_lookup, p.user.twitch_avatar_url)
        participants.append(
            {
                "name": p.user.twitch_display_name or p.user.twitch_username,
                "avatar_b64": _b64(avatar_bytes),
            }
        )
    organizer_avatar = await _resolve(avatar_lookup, race.organizer.twitch_avatar_url)
    winner_dict = None
    if winner_p is not None:
        winner_avatar = await _resolve(avatar_lookup, winner_p.user.twitch_avatar_url)
        winner_dict = {
            "name": winner_p.user.twitch_display_name or winner_p.user.twitch_username,
            "avatar_b64": _b64(winner_avatar),
        }
    return {
        "race_name": _truncate(race.name, _MAX_RACE_NAME),
        "status_label": STATUS_LABEL[race.status],
        "accent_color": ACCENT_COLOR[race.status],
        "pool_name": format_pool(race),
        "participant_count_label": _participant_count_label(race),
        "organizer_name": race.organizer.twitch_display_name or race.organizer.twitch_username,
        "organizer_avatar_b64": _b64(organizer_avatar),
        "participants": participants,
        "overflow_count": overflow,
        "winner": winner_dict,
        "scheduled_label": (
            _format_scheduled(race.scheduled_at, getattr(race.organizer, "timezone", None))
            if race.status == RaceStatus.SETUP
            else None
        ),
    }


def _cache_key(race: Race) -> str:
    if race.status == RaceStatus.FINISHED:
        finishers = sorted(
            (
                (str(p.user_id), p.igt_ms)
                for p in race.participants
                if p.status == ParticipantStatus.FINISHED
            ),
            key=lambda t: t[1],
        )
        snapshot = "F:" + "|".join(f"{uid}@{igt}" for uid, igt in finishers)
    else:
        ids = sorted(str(p.user_id) for p in race.participants)
        scheduled = int(race.scheduled_at.timestamp()) if race.scheduled_at else "none"
        tz = getattr(race.organizer, "timezone", None) or "utc"
        snapshot = (
            race.status.value
            + ":"
            + ",".join(ids)
            + f"|max={race.max_participants}"
            + f"|sched={scheduled}"
            + f"|tz={tz}"
        )
    return hashlib.sha256(snapshot.encode("utf-8")).hexdigest()[:8]


async def render_race_og(
    race: Race,
    *,
    cache_dir: Path,
    avatar_lookup: AvatarLookup,
) -> tuple[bytes, str]:
    cache_dir.mkdir(parents=True, exist_ok=True)
    key = _cache_key(race)
    cached = cache_dir / f"{race.id}-{key}.png"
    if cached.exists():
        return cached.read_bytes(), key
    ctx = await build_context(race, avatar_lookup=avatar_lookup)
    svg = render_svg(race.status.value, ctx)
    png = await asyncio.to_thread(rasterize_svg, svg)
    cached.write_bytes(png)
    return png, key
