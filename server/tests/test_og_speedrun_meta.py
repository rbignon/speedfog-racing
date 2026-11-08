"""Integration tests for /api/og/speedrun/* meta and PNG endpoints."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Pool, RunMode

from .test_set_seed_service import _seed
from .test_speedrun_service import _add_run, _user

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
    maker = async_sessionmaker(og_async_engine, class_=AsyncSession, expire_on_commit=False)
    async with maker() as db:
        db.add(Pool(name="sprint", config={"name": "Sprint", "type": "race", "layers_count": 15}))
        await db.commit()
    return maker


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


@pytest.fixture
async def sprint_runs(og_async_session_maker) -> None:
    """a: a blind deathless race at 61s; b: a Set Seed replay at 59s, and a
    blind race at 62s on the seed 5eed00000001."""
    async with og_async_session_maker() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        seed = await _seed(db, "5eed00000001")
        await _add_run(db, user=a, igt_ms=61000, minute=1, deathless=True)
        await _add_run(db, user=b, igt_ms=59000, minute=2, mode=RunMode.SET_SEED, seed=seed)
        await _add_run(db, user=b, igt_ms=62000, minute=3, seed=seed)
        await db.commit()


async def test_board_meta_shows_the_record_and_links_the_png(og_test_client, sprint_runs) -> None:
    r = await og_test_client.get("/api/og/speedrun/meta?pool=sprint")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/html")
    body = r.text
    assert "Sprint · Set Seed · Speedrun" in body
    assert "World record 0m 59s by b · Replay, 1 October 2026 · 2 players" in body
    assert "/api/og/speedrun.png?pool=sprint" in body
    assert "/speedrun?pool=sprint" in body


async def test_board_meta_follows_the_shared_board_filters(og_test_client, sprint_runs) -> None:
    """Random Seed keeps blind runs only, Deathless the deathless ones: a's
    61s race is the record there, not b's 59s replay."""
    r = await og_test_client.get("/api/og/speedrun/meta?pool=sprint&sub=random&deathless=1")
    assert r.status_code == 200
    body = r.text
    assert "Sprint · Random Seed · Deathless · Speedrun" in body
    assert "World record 1m 01s by a · Blind, 1 October 2026 · 1 player" in body
    assert "/api/og/speedrun.png?pool=sprint&amp;sub=random&amp;deathless=1" in body


async def test_board_meta_unknown_pool_shows_the_first_category(
    og_test_client, sprint_runs
) -> None:
    r = await og_test_client.get("/api/og/speedrun/meta?pool=nope&types=bogus")
    assert r.status_code == 200
    assert "Sprint · Set Seed · Speedrun" in r.text
    assert "/api/og/speedrun.png?pool=sprint" in r.text


async def test_board_meta_without_any_run_falls_back(og_test_client) -> None:
    r = await og_test_client.get("/api/og/speedrun/meta")
    assert r.status_code == 200
    assert "/og-image.png" in r.text


async def test_board_image_returns_png(og_test_client, sprint_runs) -> None:
    r = await og_test_client.get("/api/og/speedrun.png?pool=sprint&sub=random")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(_PNG_MAGIC)


async def test_board_image_redirects_without_any_run(og_test_client) -> None:
    r = await og_test_client.get("/api/og/speedrun.png", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/og-image.png")


async def test_seed_meta_shows_the_record_and_the_status(og_test_client, sprint_runs) -> None:
    r = await og_test_client.get("/api/og/speedrun/seed/5eed00000001/meta")
    assert r.status_code == 200
    body = r.text
    assert "Seed 5eed00000001 · Sprint · SpeedFog Racing" in body
    assert "Record 0m 59s by b · Replay, 1 October 2026 · 2 runs · 1 player · Replayable" in body
    assert "/api/og/speedrun/seed/5eed00000001.png" in body
    assert "/speedrun/seed/5eed00000001" in body


async def test_seed_meta_with_unranked_runs_only_counts_them(
    og_test_client, og_async_session_maker
) -> None:
    """A race drawn on a seen seed counts on no board: its seed page lists the
    run unranked, and so must the card, with no record."""
    async with og_async_session_maker() as db:
        a = await _user(db, "a")
        seed = await _seed(db, "5eed00000002")
        await _add_run(db, user=a, igt_ms=61000, minute=1, seed=seed, seed_was_seen=True)
        await db.commit()

    r = await og_test_client.get("/api/og/speedrun/seed/5eed00000002/meta")
    assert r.status_code == 200
    assert "No ranked run yet · 1 run · 1 player · Replayable" in r.text


async def test_seed_meta_unknown_seed_falls_back(og_test_client, sprint_runs) -> None:
    r = await og_test_client.get("/api/og/speedrun/seed/000000000000/meta")
    assert r.status_code == 200
    assert "/og-image.png" in r.text


async def test_seed_image_returns_png(og_test_client, sprint_runs) -> None:
    r = await og_test_client.get("/api/og/speedrun/seed/5eed00000001.png")
    assert r.status_code == 200
    assert r.headers["content-type"] == "image/png"
    assert r.content.startswith(_PNG_MAGIC)


async def test_seed_image_redirects_when_render_fails(
    og_test_client, sprint_runs, monkeypatch
) -> None:
    async def _boom(*args, **kwargs):
        raise RuntimeError("resvg crashed")

    monkeypatch.setattr("speedfog_racing.api.og.render_speedrun_seed_og", _boom)
    r = await og_test_client.get("/api/og/speedrun/seed/5eed00000001.png", follow_redirects=False)
    assert r.status_code == 302
    assert r.headers["location"].endswith("/og-image.png")
