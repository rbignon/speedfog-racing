"""Integration tests for OG meta + PNG endpoints."""

from __future__ import annotations

import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Race, RaceStatus, Seed, SeedStatus, User, UserRole


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
async def organizer(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="og_org",
            twitch_username="organizer",
            twitch_display_name="The Organizer",
            api_token="og_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number="og123",
            pool_name="standard",
            graph_json={"total_layers": 10, "nodes": []},
            total_layers=10,
            folder_path="/tmp/og.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


@pytest.fixture
async def setup_race(async_session, organizer, seed):
    async with async_session() as db:
        race = Race(
            name="Friday Night Fog",
            organizer_id=organizer.id,
            status=RaceStatus.SETUP,
            seed_id=seed.id,
            is_public=True,
            max_participants=20,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return race


@pytest.fixture
def client(async_session):
    async def override_get_db():
        async with async_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_meta_endpoint_returns_html_with_og_tags(client, setup_race):
    async with client as c:
        r = await c.get(f"/api/og/race/{setup_race.id}/meta")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert '<meta property="og:title"' in body
    assert "Friday Night Fog" in body
    assert f"/api/og/race/{setup_race.id}.png" in body
    assert '<meta property="og:type" content="website"' in body


@pytest.mark.asyncio
async def test_meta_endpoint_unknown_race_returns_default_html(client):
    async with client as c:
        r = await c.get(f"/api/og/race/{uuid.uuid4()}/meta")
    assert r.status_code == 200
    assert "/og-image.png" in r.text


@pytest.mark.asyncio
async def test_png_endpoint_returns_png_with_cache_headers(client, setup_race):
    async with client as c:
        r = await c.get(f"/api/og/race/{setup_race.id}.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert "max-age=300" in r.headers["cache-control"]


@pytest.mark.asyncio
async def test_png_endpoint_unknown_race_redirects_to_static(client):
    async with client as c:
        r = await c.get(f"/api/og/race/{uuid.uuid4()}.png", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/og-image.png")
