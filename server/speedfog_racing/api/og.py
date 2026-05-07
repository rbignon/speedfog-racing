"""Open Graph endpoints: dynamic meta HTML + rasterized PNG per race."""

from __future__ import annotations

import datetime as dt
import functools
import logging
from html import escape
from pathlib import Path
from uuid import UUID

from fastapi import APIRouter, Depends, Response
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from speedfog_racing.config import settings
from speedfog_racing.database import get_db
from speedfog_racing.models import Participant, Race
from speedfog_racing.services.avatar_cache import AvatarCache
from speedfog_racing.services.daily_seed_loop import daily_date_for
from speedfog_racing.services.og_image import (
    STATUS_LABEL,
    format_daily_date,
    format_pool,
    render_daily_og,
    render_race_og,
)

logger = logging.getLogger(__name__)

router = APIRouter()

_DEFAULT_AVATAR_PATH = (
    Path(__file__).resolve().parent.parent / "static" / "og" / "default-avatar.png"
)
_DEFAULT_OG_HTML_TEMPLATE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"/>
<meta property="og:site_name" content="SpeedFog Racing"/>
<meta property="og:type" content="website"/>
<meta property="og:title" content="{title}"/>
<meta property="og:description" content="{description}"/>
<meta property="og:url" content="{url}"/>
<meta property="og:image" content="{image}"/>
<meta property="twitter:card" content="summary_large_image"/>
<meta property="twitter:image" content="{image}"/>
<title>{title}</title>
</head><body></body></html>
"""

_DEFAULT_TITLE = "SpeedFog Racing"
_DEFAULT_DESCRIPTION = (
    "Competitive Elden Ring Fog Randomizer racing platform. "
    "Race against other players through randomized fog gates in real time."
)


@functools.lru_cache(maxsize=1)
def _avatar_cache() -> AvatarCache:
    cache_dir = Path(settings.og_cache_dir).expanduser() / "avatars"
    return AvatarCache(cache_dir=cache_dir, default_avatar=_DEFAULT_AVATAR_PATH.read_bytes())


def _render_html(*, title: str, description: str, og_url: str, og_image: str) -> str:
    return _DEFAULT_OG_HTML_TEMPLATE.format(
        title=escape(title),
        description=escape(description),
        url=escape(og_url),
        image=escape(og_image),
    )


async def _load_race(db: AsyncSession, race_id: UUID) -> Race | None:
    query = (
        select(Race)
        .where(Race.id == race_id)
        .options(
            selectinload(Race.organizer),
            selectinload(Race.participants).selectinload(Participant.user),
            selectinload(Race.seed),
        )
    )
    result = await db.execute(query)
    return result.scalar_one_or_none()


async def _load_daily(db: AsyncSession, daily_date: dt.date) -> Race | None:
    query = select(Race).where(Race.daily_date == daily_date).options(selectinload(Race.seed))
    result = await db.execute(query)
    return result.scalar_one_or_none()


def _daily_meta_html(race: Race | None, *, share_url: str, image_url: str) -> str:
    base = settings.base_url.rstrip("/")
    if race is None:
        return _render_html(
            title=_DEFAULT_TITLE,
            description=_DEFAULT_DESCRIPTION,
            og_url=base + "/",
            og_image=base + "/og-image.png",
        )
    assert race.daily_date is not None
    date_label = format_daily_date(race.daily_date)
    pool_display = format_pool(race)
    title = f"Daily Seed - {date_label} · SpeedFog Racing"
    description = (
        f"Daily Seed for {date_label} · {pool_display} pool. "
        "Race the same seed as everyone else, "
        "compare your time on the daily leaderboard."
    )
    return _render_html(
        title=title,
        description=description,
        og_url=share_url,
        og_image=image_url,
    )


async def _serve_daily_png(race: Race | None) -> Response:
    base = settings.base_url.rstrip("/")
    fallback = RedirectResponse(url=f"{base}/og-image.png", status_code=302)
    if race is None:
        return fallback
    try:
        cache_dir = Path(settings.og_cache_dir).expanduser()
        png = await render_daily_og(race, cache_dir=cache_dir)
    except Exception:
        logger.exception("og daily image render failed for date=%s", race.daily_date)
        return fallback
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=86400, stale-while-revalidate=604800"},
    )


@router.get("/daily/today/meta", response_class=HTMLResponse)
async def og_daily_today_meta(db: AsyncSession = Depends(get_db)) -> Response:
    base = settings.base_url.rstrip("/")
    today = daily_date_for(dt.datetime.now(dt.UTC))
    try:
        race = await _load_daily(db, today)
    except Exception:
        logger.exception("og daily meta load failed for today=%s", today)
        race = None
    html = _daily_meta_html(
        race,
        share_url=f"{base}/daily",
        image_url=f"{base}/api/og/daily/today.png",
    )
    return HTMLResponse(content=html, headers={"Cache-Control": "public, max-age=300"})


@router.get("/daily/{daily_date}/meta", response_class=HTMLResponse)
async def og_daily_meta(daily_date: dt.date, db: AsyncSession = Depends(get_db)) -> Response:
    base = settings.base_url.rstrip("/")
    try:
        race = await _load_daily(db, daily_date)
    except Exception:
        logger.exception("og daily meta load failed for date=%s", daily_date)
        race = None
    html = _daily_meta_html(
        race,
        share_url=f"{base}/daily/{daily_date.isoformat()}",
        image_url=f"{base}/api/og/daily/{daily_date.isoformat()}.png",
    )
    return HTMLResponse(content=html, headers={"Cache-Control": "public, max-age=300"})


@router.get("/daily/today.png")
async def og_daily_today_image(db: AsyncSession = Depends(get_db)) -> Response:
    today = daily_date_for(dt.datetime.now(dt.UTC))
    try:
        race = await _load_daily(db, today)
    except Exception:
        logger.exception("og daily image load failed for today=%s", today)
        race = None
    return await _serve_daily_png(race)


@router.get("/daily/{daily_date}.png")
async def og_daily_image(daily_date: dt.date, db: AsyncSession = Depends(get_db)) -> Response:
    try:
        race = await _load_daily(db, daily_date)
    except Exception:
        logger.exception("og daily image load failed for date=%s", daily_date)
        race = None
    return await _serve_daily_png(race)


@router.get("/race/{race_id}/meta", response_class=HTMLResponse)
async def og_race_meta(race_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    """HTML stub with race-specific OG tags. Served to crawlers via nginx."""
    try:
        race = await _load_race(db, race_id)
    except Exception:
        logger.exception("og meta load failed for %s", race_id)
        race = None
    base = settings.base_url.rstrip("/")
    if race is None:
        html = _render_html(
            title=_DEFAULT_TITLE,
            description=_DEFAULT_DESCRIPTION,
            og_url=base + "/",
            og_image=base + "/og-image.png",
        )
    else:
        title = f"{race.name} · SpeedFog Racing"
        status_label = STATUS_LABEL[race.status]
        description = (
            f"{status_label} race · {len(race.participants)} player(s) · "
            f"{format_pool(race)} · hosted by "
            f"{race.organizer.twitch_display_name or race.organizer.twitch_username}"
        )
        html = _render_html(
            title=title,
            description=description,
            og_url=f"{base}/race/{race.id}",
            og_image=f"{base}/api/og/race/{race.id}.png",
        )
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "public, max-age=60"},
    )


@router.get("/race/{race_id}.png")
async def og_race_image(race_id: UUID, db: AsyncSession = Depends(get_db)) -> Response:
    """Rasterized OG image. Cached on disk per (race_id, race_state)."""
    base = settings.base_url.rstrip("/")
    fallback = RedirectResponse(url=f"{base}/og-image.png", status_code=302)
    try:
        race = await _load_race(db, race_id)
    except Exception:
        logger.exception("og image load failed for %s", race_id)
        return fallback
    if race is None:
        return fallback
    try:
        cache_dir = Path(settings.og_cache_dir).expanduser()
        cache = _avatar_cache()
        png, _ = await render_race_og(race, cache_dir=cache_dir, avatar_lookup=cache.get)
    except Exception:
        logger.exception("og image render failed for %s", race_id)
        return fallback
    return Response(
        content=png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=300, stale-while-revalidate=3600"},
    )
