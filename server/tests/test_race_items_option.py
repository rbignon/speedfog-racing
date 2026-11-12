"""The race_items race option: create, edit and RaceInfo plumbing."""

import uuid
from datetime import UTC, date, datetime

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Event,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedStatus,
    User,
    UserRole,
)

pytestmark = pytest.mark.asyncio


@pytest.fixture
async def ri_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def ri_async_session(ri_async_engine):
    return async_sessionmaker(ri_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def ri_test_client(ri_async_session):
    async def override_get_db():
        async with ri_async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def ri_organizer(ri_async_session):
    async with ri_async_session() as db:
        user = User(
            twitch_id="org_ri",
            twitch_username="organizer_ri",
            twitch_display_name="Organizer DL",
            api_token="org_ri_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def ri_player(ri_async_session):
    async with ri_async_session() as db:
        user = User(
            twitch_id="player_ri",
            twitch_username="player_ri",
            twitch_display_name="Player DL",
            api_token="player_ri_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _make_seed(db, *, suffix: str, status: SeedStatus = SeedStatus.AVAILABLE) -> Seed:
    seed = Seed(
        seed_number=f"ri_{suffix}",
        pool_name="standard",
        graph_json={
            "total_layers": 5,
            "nodes": [],
            "plugins": {"race_items": {"enabled": True}},
            "race_items": {"shield": {"name": "Shield", "icon": "shield", "goods_id": 1}},
        },
        total_layers=5,
        folder_path=f"/test/ri_{suffix}",
        status=status,
    )
    db.add(seed)
    await db.flush()
    return seed


def _auth(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.api_token}"}


async def _setup_race(db, organizer, *, suffix: str, **kwargs) -> uuid.UUID:
    seed = await _make_seed(db, suffix=suffix, status=SeedStatus.CONSUMED)
    race = Race(
        name=f"Race {suffix}",
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=kwargs.pop("status", RaceStatus.SETUP),
        **kwargs,
    )
    db.add(race)
    await db.commit()
    return race.id


async def test_create_race_with_race_items(ri_test_client, ri_async_session, ri_organizer):
    async with ri_async_session() as db:
        await _make_seed(db, suffix="create")
        await db.commit()

    async with ri_test_client as client:
        resp = await client.post(
            "/api/races",
            json={"name": "Items race", "race_items": True},
            headers=_auth(ri_organizer),
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["race_items"] is True
    async with ri_async_session() as db:
        race = (await db.execute(select(Race))).scalar_one()
        assert race.race_items is True


async def test_create_race_items_rejects_speedrun_mode(
    ri_test_client, ri_async_session, ri_organizer
):
    async with ri_async_session() as db:
        await _make_seed(db, suffix="speedrun")
        await db.commit()

    async with ri_test_client as client:
        resp = await client.post(
            "/api/races",
            json={"name": "Speedrun items", "mode": "speedrun", "race_items": True},
            headers=_auth(ri_organizer),
        )
    assert resp.status_code == 422, resp.text


async def test_edit_race_items_in_setup(
    ri_test_client, ri_async_session, ri_organizer, monkeypatch
):
    from unittest.mock import AsyncMock

    from speedfog_racing.api import races as races_api

    broadcast = AsyncMock()
    monkeypatch.setattr(races_api, "broadcast_race_info_update", broadcast)
    async with ri_async_session() as db:
        race_id = await _setup_race(db, ri_organizer, suffix="edit")

    async with ri_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}", json={"race_items": True}, headers=_auth(ri_organizer)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["race_items"] is True
        assert broadcast.await_count == 1
        resp = await client.patch(
            f"/api/races/{race_id}", json={"race_items": False}, headers=_auth(ri_organizer)
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["race_items"] is False
        assert broadcast.await_count == 2


async def test_edit_race_items_rejected_once_running(
    ri_test_client, ri_async_session, ri_organizer
):
    async with ri_async_session() as db:
        race_id = await _setup_race(
            db,
            ri_organizer,
            suffix="running",
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )

    async with ri_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}", json={"race_items": True}, headers=_auth(ri_organizer)
        )
    assert resp.status_code == 400
    assert "race_items" in resp.json()["detail"]


async def test_edit_race_items_rejected_on_non_community_race(
    ri_test_client, ri_async_session, ri_organizer
):
    async with ri_async_session() as db:
        daily = await _setup_race(db, ri_organizer, suffix="daily", daily_date=date(2026, 11, 12))
        speedrun = await _setup_race(db, ri_organizer, suffix="sr", mode=RunMode.SPEEDRUN)
        event = Event(
            slug="ri-ev",
            name="Ri Event",
            starts_at=datetime.now(UTC),
            qualifier_ends_at=datetime.now(UTC),
            ends_at=datetime.now(UTC),
        )
        db.add(event)
        await db.flush()
        in_event = await _setup_race(
            db, ri_organizer, suffix="event", event_id=event.id, event_slot="r1"
        )

    async with ri_test_client as client:
        for race_id in (daily, speedrun, in_event):
            resp = await client.patch(
                f"/api/races/{race_id}", json={"race_items": True}, headers=_auth(ri_organizer)
            )
            assert resp.status_code == 400, resp.text


async def test_race_items_and_deathless_combine(ri_test_client, ri_async_session, ri_organizer):
    async with ri_async_session() as db:
        await _make_seed(db, suffix="combine")
        await db.commit()

    async with ri_test_client as client:
        resp = await client.post(
            "/api/races",
            json={"name": "Both", "race_items": True, "deathless": True},
            headers=_auth(ri_organizer),
        )
    assert resp.status_code == 201, resp.text
    assert resp.json()["race_items"] is True
    assert resp.json()["deathless"] is True


async def test_race_info_carries_race_items(ri_async_session, ri_organizer):
    from speedfog_racing.websocket.schemas import build_race_info

    async with ri_async_session() as db:
        race_id = await _setup_race(db, ri_organizer, suffix="info", race_items=True)
        race = (
            await db.execute(
                select(Race).where(Race.id == race_id).options(selectinload(Race.seed))
            )
        ).scalar_one()
        assert build_race_info(race).race_items is True
