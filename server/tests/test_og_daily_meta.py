"""Integration tests for /api/og/daily/* meta and PNG endpoints."""

from __future__ import annotations

import datetime as dt
from datetime import UTC

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Pool, Race, RaceStatus, Seed, SeedStatus, User, UserRole
from speedfog_racing.services.daily_seed_loop import daily_date_for

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


@pytest.fixture(autouse=True)
def _isolate_og_cache(tmp_path, monkeypatch):
    import speedfog_racing.config as cfg

    monkeypatch.setattr(cfg.settings, "og_cache_dir", str(tmp_path / "og"))


@pytest.fixture
async def og_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def og_async_session_maker(og_async_engine):
    return async_sessionmaker(og_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def og_test_client(og_async_session_maker):
    async def override_get_db():
        async with og_async_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _make_daily_db(
    session_maker,
    *,
    day: dt.date,
    pool_display_name: str = "Standard",
    status: RaceStatus = RaceStatus.RUNNING,
) -> Race:
    """Insert a daily race with a pool/seed into the test DB and return the persisted row."""
    # Use the date as part of the pool name to keep each insert unique within a shared DB.
    pool_name = f"pool-{day.isoformat()}"
    async with session_maker() as db:
        pool = Pool(
            name=pool_name,
            config={"name": pool_display_name},
        )
        db.add(pool)
        await db.flush()

        seed = Seed(
            seed_number=f"seed-{day.isoformat()}",
            pool_name=pool_name,
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path=f"/tmp/daily-{day.isoformat()}.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.flush()

        organizer = User(
            twitch_id=f"sys-{day.isoformat()}",
            twitch_username=f"sys_{day.isoformat()}",
            twitch_display_name="System",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        db.add(organizer)
        await db.flush()

        started = dt.datetime.combine(day, dt.time(8, 0), tzinfo=UTC)
        race = Race(
            name=f"Daily Seed - {day.isoformat()}",
            organizer_id=organizer.id,
            status=status,
            is_public=True,
            open_registration=True,
            daily_date=day,
            exclude_from_stats=True,
            started_at=started,
            seeds_released_at=started,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
            seed_id=seed.id,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return race


@pytest.mark.asyncio
async def test_daily_meta_returns_html_with_date_in_title(
    og_test_client, og_async_session_maker
) -> None:
    await _make_daily_db(og_async_session_maker, day=dt.date(2026, 4, 27))
    r = await og_test_client.get("/api/og/daily/2026-04-27/meta")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "Monday 27 April 2026" in body
    assert "Standard" in body
    assert "/api/og/daily/2026-04-27.png" in body


@pytest.mark.asyncio
async def test_daily_meta_today_resolves_current_daily(
    og_test_client, og_async_session_maker
) -> None:
    today = daily_date_for(dt.datetime.now(UTC))
    await _make_daily_db(og_async_session_maker, day=today, pool_display_name="Sprint")
    r = await og_test_client.get("/api/og/daily/today/meta")
    assert r.status_code == 200
    body = r.text
    assert "Sprint" in body
    # The canonical share URL for today must be /daily (no date segment).
    assert '/daily"' in body
    assert f"/daily/{today.isoformat()}" not in body


@pytest.mark.asyncio
async def test_daily_meta_falls_back_when_daily_missing(og_test_client) -> None:
    r = await og_test_client.get("/api/og/daily/2099-01-01/meta")
    assert r.status_code == 200
    assert "/og-image.png" in r.text


@pytest.mark.asyncio
async def test_daily_image_returns_png(og_test_client, og_async_session_maker) -> None:
    await _make_daily_db(og_async_session_maker, day=dt.date(2026, 4, 27))
    r = await og_test_client.get("/api/og/daily/2026-04-27.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(_PNG_MAGIC)
    assert "max-age=86400" in r.headers["cache-control"]


@pytest.mark.asyncio
async def test_daily_image_redirects_when_daily_missing(og_test_client) -> None:
    r = await og_test_client.get("/api/og/daily/2099-01-01.png", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/og-image.png")


@pytest.mark.asyncio
async def test_daily_image_today_resolves_current_daily(
    og_test_client, og_async_session_maker
) -> None:
    today = daily_date_for(dt.datetime.now(UTC))
    await _make_daily_db(og_async_session_maker, day=today)
    r = await og_test_client.get("/api/og/daily/today.png")
    assert r.status_code == 200
    assert r.content.startswith(_PNG_MAGIC)


@pytest.mark.asyncio
async def test_daily_image_redirects_when_render_fails(
    og_test_client, og_async_session_maker, monkeypatch
) -> None:
    target = dt.date(2026, 4, 27)
    await _make_daily_db(og_async_session_maker, day=target)

    async def _boom(*args, **kwargs):
        raise RuntimeError("resvg crashed")

    monkeypatch.setattr("speedfog_racing.api.og.render_daily_og", _boom)
    response = await og_test_client.get(
        f"/api/og/daily/{target.isoformat()}.png", follow_redirects=False
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith("/og-image.png")
