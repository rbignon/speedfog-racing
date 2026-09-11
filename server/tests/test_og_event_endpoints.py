"""Integration tests for the event OG meta + PNG endpoints."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import speedfog_racing.api.og as og_api
from speedfog_racing.config import settings
from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Event,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)

T0 = datetime(2026, 9, 23, 8, tzinfo=UTC)
CONFIG = {
    "modes": [{"key": "standard", "label": "Standard"}],
    "seeds_per_mode": 1,
    "stages": [
        {
            "key": "semi_a",
            "label": "Semi A",
            "kind": "semi",
            "date": "2026-10-04T19:00:00Z",
            "races": 1,
            "seeds": [1, 2],
        },
        {
            "key": "final",
            "label": "Open final",
            "kind": "final",
            "date": "2026-10-25T19:00:00Z",
            "races": 1,
            "from": ["semi_a"],
            "advance": 2,
        },
    ],
    "phase_override": "qualifier",
}


@pytest.fixture(autouse=True)
def _isolate_og_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "og_cache_dir", str(tmp_path / "og"))
    og_api._avatar_cache.cache_clear()
    og_api._logo_cache.cache_clear()
    yield
    og_api._avatar_cache.cache_clear()
    og_api._logo_cache.cache_clear()


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
def client(async_session):
    async def override_get_db():
        async with async_session() as db:
            yield db

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    yield AsyncClient(transport=transport, base_url="http://test")
    app.dependency_overrides.clear()


@pytest.fixture
async def event(async_session):
    """An event in its qualifier week, with one seed and two runners.

    Avatar URLs stay empty on purpose: the OG renderer then serves its bundled
    default avatar instead of reaching for Twitch's CDN during the test.
    """
    async with async_session() as db:
        orga = User(
            twitch_id="ev_org",
            twitch_username="orga",
            api_token="ev_org_token",
            role=UserRole.ORGANIZER,
        )
        ana = User(twitch_id="ev_ana", twitch_username="ana", api_token="ev_ana_token")
        bob = User(twitch_id="ev_bob", twitch_username="bob", api_token="ev_bob_token")
        db.add_all([orga, ana, bob])
        await db.flush()
        row = Event(
            slug="season-one",
            name="Season One",
            partner_name="Ignite",
            starts_at=T0,
            qualifier_ends_at=T0 + timedelta(days=7),
            ends_at=datetime(2026, 10, 26, tzinfo=UTC),
            newcomer_threshold=5,
            config=CONFIG,
        )
        seed = Seed(
            seed_number="ev1",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/seeds/ev1.zip",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([row, seed])
        await db.flush()
        race = Race(
            name="Season One qualifier - Standard - Seed 1",
            organizer_id=orga.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=T0,
            event_id=row.id,
            event_slot="qualifier:standard:1",
        )
        db.add(race)
        await db.flush()
        for user, igt in ((ana, 1_000_000), (bob, 1_200_000)):
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user.id,
                    status=ParticipantStatus.FINISHED,
                    igt_ms=igt,
                    current_layer=4,
                    zone_history=[{"node_id": "a"}, {"node_id": "b"}],
                )
            )
        await db.commit()
        return row


async def test_meta_endpoint_describes_the_event(client, event):
    async with client as c:
        r = await c.get("/api/og/event/season-one/meta")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert '<meta property="og:title"' in body
    assert "Season One" in body
    assert "Ignite" in body
    assert "/api/og/event/season-one.png" in body


async def test_meta_endpoint_description_reports_the_phase(client, event):
    async with client as c:
        r = await c.get("/api/og/event/season-one/meta")
    assert "Qualifier closes on 30 September" in r.text
    assert "2 players" in r.text


async def test_meta_endpoint_unknown_event_returns_default_html(client):
    async with client as c:
        r = await c.get("/api/og/event/nope/meta")
    assert r.status_code == 200
    assert "/og-image.png" in r.text


async def test_png_endpoint_returns_png_with_cache_headers(client, event):
    async with client as c:
        r = await c.get("/api/og/event/season-one.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(b"\x89PNG\r\n\x1a\n")
    assert "max-age=300" in r.headers["cache-control"]


async def test_png_endpoint_unknown_event_redirects_to_static(client):
    async with client as c:
        r = await c.get("/api/og/event/nope.png", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/og-image.png")


async def test_meta_title_is_not_cut_down_to_the_card_size(client, event, async_session):
    """The card truncates a long event name to fit; a title has no such limit."""
    long_name = "Season One of the Ignite Invitational Championship"
    async with async_session() as db:
        await db.execute(update(Event).where(Event.slug == "season-one").values(name=long_name))
        await db.commit()
    async with client as c:
        r = await c.get("/api/og/event/season-one/meta")
    assert long_name in r.text


async def test_meta_endpoint_falls_back_when_the_stored_config_is_invalid(
    client, event, async_session
):
    """The page validates the stored config on every request; so does the card."""
    async with async_session() as db:
        await db.execute(update(Event).where(Event.slug == "season-one").values(config={}))
        await db.commit()
    async with client as c:
        r = await c.get("/api/og/event/season-one/meta")
    assert r.status_code == 200
    assert "/og-image.png" in r.text


async def test_png_endpoint_falls_back_when_the_stored_config_is_invalid(
    client, event, async_session
):
    async with async_session() as db:
        await db.execute(update(Event).where(Event.slug == "season-one").values(config={}))
        await db.commit()
    async with client as c:
        r = await c.get("/api/og/event/season-one.png", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/og-image.png")
