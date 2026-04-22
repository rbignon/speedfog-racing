"""Test feedback API endpoints."""

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Feedback,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
)


@pytest.fixture
async def async_engine():
    """Create async test database engine."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def async_session(async_engine):
    """Create async session factory."""
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def test_client(async_session):
    """Create test client with async database override."""

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _create_user(async_session, username: str = "player1") -> User:
    async with async_session() as db:
        user = User(
            twitch_id=f"tw_{username}",
            twitch_username=username,
            twitch_display_name=username,
            api_token=f"tok_{username}",
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


def _auth_headers(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {user.api_token}"}


@pytest.mark.asyncio
async def test_post_feedback_user_menu_ok(test_client, async_session):
    user = await _create_user(async_session)
    async with test_client as client:
        r = await client.post(
            "/api/feedback",
            json={"rating": 4, "comment": "great", "source": "user_menu"},
            headers=_auth_headers(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["rating"] == 4
        assert body["source"] == "user_menu"
        assert body["race_id"] is None
        assert body["races_played_at_feedback"] == 0

    async with async_session() as db:
        result = await db.execute(select(Feedback).where(Feedback.user_id == user.id))
        rows = result.scalars().all()
        assert len(rows) == 1


@pytest.mark.asyncio
async def test_post_feedback_post_first_race_ok(test_client, async_session):
    user = await _create_user(async_session)
    async with async_session() as db:
        race = Race(name="r1", status=RaceStatus.FINISHED, organizer_id=user.id)
        db.add(race)
        await db.commit()
        await db.refresh(race)
        participant = Participant(
            race_id=race.id, user_id=user.id, status=ParticipantStatus.FINISHED
        )
        db.add(participant)
        await db.commit()
        race_id = race.id

    async with test_client as client:
        r = await client.post(
            "/api/feedback",
            json={
                "rating": 5,
                "comment": None,
                "source": "post_first_race",
                "race_id": str(race_id),
            },
            headers=_auth_headers(user),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["race_id"] == str(race_id)
        assert body["races_played_at_feedback"] == 1


@pytest.mark.asyncio
async def test_post_feedback_rejects_rating_out_of_range(test_client, async_session):
    user = await _create_user(async_session)
    async with test_client as client:
        r = await client.post(
            "/api/feedback",
            json={"rating": 0, "source": "user_menu"},
            headers=_auth_headers(user),
        )
        assert r.status_code == 422


@pytest.mark.asyncio
async def test_post_feedback_user_menu_rejects_race_id(test_client, async_session):
    user = await _create_user(async_session)
    async with test_client as client:
        r = await client.post(
            "/api/feedback",
            json={"rating": 3, "source": "user_menu", "race_id": str(uuid4())},
            headers=_auth_headers(user),
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_post_feedback_first_race_requires_race_id(test_client, async_session):
    user = await _create_user(async_session)
    async with test_client as client:
        r = await client.post(
            "/api/feedback",
            json={"rating": 3, "source": "post_first_race"},
            headers=_auth_headers(user),
        )
        assert r.status_code == 400


@pytest.mark.asyncio
async def test_post_feedback_first_race_requires_participant(test_client, async_session):
    user = await _create_user(async_session)
    other = await _create_user(async_session, "other")
    async with async_session() as db:
        race = Race(name="r", status=RaceStatus.FINISHED, organizer_id=other.id)
        db.add(race)
        await db.commit()
        await db.refresh(race)
        race_id = race.id

    async with test_client as client:
        r = await client.post(
            "/api/feedback",
            json={"rating": 4, "source": "post_first_race", "race_id": str(race_id)},
            headers=_auth_headers(user),
        )
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_post_feedback_requires_auth(test_client):
    async with test_client as client:
        r = await client.post("/api/feedback", json={"rating": 4, "source": "user_menu"})
        assert r.status_code in (401, 403)
