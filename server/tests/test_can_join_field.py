"""Tests for can_join field on race responses."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Caster,
    Participant,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)


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
            twitch_id="cj_org",
            twitch_username="cj_org",
            twitch_display_name="Organizer",
            api_token="cj_org_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def player(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="cj_player",
            twitch_username="cj_player",
            twitch_display_name="Player",
            api_token="cj_player_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number="cj_seed",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/cj_seed.zip",
            status=SeedStatus.AVAILABLE,
        )
        db.add(s)
        await db.commit()
        await db.refresh(s)
        return s


@pytest.fixture
def test_client(async_session):
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _create_race(
    db, organizer, seed, *, open_registration=True, max_participants=None, status=RaceStatus.SETUP
):
    """Helper to create a race directly in the DB."""
    race = Race(
        name="Test Race",
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=status,
        open_registration=open_registration,
        max_participants=max_participants,
    )
    db.add(race)
    await db.commit()
    await db.refresh(race)
    return race


@pytest.mark.asyncio
async def test_can_join_true_for_open_setup_race(
    test_client, organizer, player, seed, async_session
):
    """Open setup race returns can_join=True for unrelated player."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is True


@pytest.mark.asyncio
async def test_can_join_false_for_organizer(test_client, organizer, seed, async_session):
    """Organizer's own open race returns can_join=False."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_for_participant(test_client, organizer, player, seed, async_session):
    """Player already in the race gets can_join=False."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed)
        db.add(Participant(race_id=race.id, user_id=player.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_for_caster(test_client, organizer, player, seed, async_session):
    """Caster gets can_join=False."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed)
        db.add(Caster(race_id=race.id, user_id=player.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_for_invite_only(test_client, organizer, player, seed, async_session):
    """Invite-only race returns can_join=False."""
    async with async_session() as db:
        await _create_race(db, organizer, seed, open_registration=False)

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_for_running_race(test_client, organizer, player, seed, async_session):
    """Running open race returns can_join=False."""
    async with async_session() as db:
        await _create_race(db, organizer, seed, status=RaceStatus.RUNNING)

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=running",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_false_when_full(test_client, organizer, player, seed, async_session):
    """Full open race returns can_join=False."""
    async with async_session() as db:
        race = await _create_race(db, organizer, seed, max_participants=1)
        filler = User(
            twitch_id="cj_filler",
            twitch_username="cj_filler",
            twitch_display_name="Filler",
            api_token="cj_filler_token",
            role=UserRole.USER,
        )
        db.add(filler)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=filler.id))
        await db.commit()

    async with test_client as client:
        resp = await client.get(
            "/api/races?status=setup",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is False


@pytest.mark.asyncio
async def test_can_join_true_unauthenticated(test_client, organizer, seed, async_session):
    """Unauthenticated users see can_join=True for open setup races (CTA)."""
    async with async_session() as db:
        await _create_race(db, organizer, seed)

    async with test_client as client:
        resp = await client.get("/api/races?status=setup")
        assert resp.status_code == 200
        races = resp.json()["races"]
        assert len(races) == 1
        assert races[0]["can_join"] is True
