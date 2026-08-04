"""Deathless race option: plumbing (Task 1) and enforcement (Task 2)."""

from datetime import UTC, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def dl_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def dl_async_session(dl_async_engine):
    return async_sessionmaker(dl_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def dl_test_client(dl_async_session):
    async def override_get_db():
        async with dl_async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def dl_organizer(dl_async_session):
    async with dl_async_session() as db:
        user = User(
            twitch_id="org_dl",
            twitch_username="organizer_dl",
            twitch_display_name="Organizer DL",
            api_token="org_dl_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def dl_player(dl_async_session):
    async with dl_async_session() as db:
        user = User(
            twitch_id="player_dl",
            twitch_username="player_dl",
            twitch_display_name="Player DL",
            api_token="player_dl_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _make_seed(db, *, suffix: str, status: SeedStatus = SeedStatus.CONSUMED) -> Seed:
    seed = Seed(
        seed_number=f"dl_{suffix}",
        pool_name="standard",
        graph_json={"total_layers": 5, "nodes": []},
        total_layers=5,
        folder_path=f"/test/dl_{suffix}",
        status=status,
    )
    db.add(seed)
    await db.flush()
    return seed


# ---------------------------------------------------------------------------
# Task 1: option plumbing
# ---------------------------------------------------------------------------


async def test_create_race_deathless_default_false(dl_test_client, dl_async_session, dl_organizer):
    async with dl_async_session() as db:
        await _make_seed(db, suffix="create_def", status=SeedStatus.AVAILABLE)
        await db.commit()

    async with dl_test_client as client:
        resp = await client.post(
            "/api/races",
            json={"name": "Plain race"},
            headers={"Authorization": f"Bearer {dl_organizer.api_token}"},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["deathless"] is False


async def test_create_race_deathless_true(dl_test_client, dl_async_session, dl_organizer):
    async with dl_async_session() as db:
        await _make_seed(db, suffix="create_on", status=SeedStatus.AVAILABLE)
        await db.commit()

    async with dl_test_client as client:
        resp = await client.post(
            "/api/races",
            json={"name": "Deathless race", "deathless": True},
            headers={"Authorization": f"Bearer {dl_organizer.api_token}"},
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["deathless"] is True


async def test_patch_deathless_setup_toggles_and_broadcasts(
    dl_test_client, dl_async_session, dl_organizer, monkeypatch
):
    from unittest.mock import AsyncMock

    from speedfog_racing.api import races as races_api

    broadcast = AsyncMock()
    monkeypatch.setattr(races_api, "broadcast_race_info_update", broadcast)

    async with dl_async_session() as db:
        seed = await _make_seed(db, suffix="patch_setup")
        race = Race(
            name="Patch deathless",
            organizer_id=dl_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with dl_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"deathless": True},
            headers={"Authorization": f"Bearer {dl_organizer.api_token}"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["deathless"] is True
    broadcast.assert_awaited_once()


async def test_patch_deathless_rejected_when_running(
    dl_test_client, dl_async_session, dl_organizer
):
    async with dl_async_session() as db:
        seed = await _make_seed(db, suffix="patch_run")
        race = Race(
            name="Running race",
            organizer_id=dl_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with dl_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"deathless": True},
            headers={"Authorization": f"Bearer {dl_organizer.api_token}"},
        )
    assert resp.status_code == 400
    assert "deathless" in resp.json()["detail"]


async def test_race_info_includes_deathless(dl_async_session, dl_organizer):
    from speedfog_racing.websocket.schemas import build_race_info

    async with dl_async_session() as db:
        seed = await _make_seed(db, suffix="raceinfo")
        race = Race(
            name="Info race",
            organizer_id=dl_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            deathless=True,
        )
        db.add(race)
        await db.commit()
        info = build_race_info(race)

    assert info.deathless is True
    assert '"deathless":true' in info.model_dump_json()
