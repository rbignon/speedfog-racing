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
    FeedbackSource,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
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


@pytest.mark.asyncio
async def test_mark_prompted_sets_timestamp(test_client, async_session):
    user = await _create_user(async_session, "promptu")
    assert user.feedback_prompted_at is None
    async with test_client as client:
        r = await client.post("/api/feedback/mark-prompted", headers=_auth_headers(user))
        assert r.status_code == 204

    async with async_session() as db:
        result = await db.execute(select(User).where(User.id == user.id))
        refreshed = result.scalar_one()
        assert refreshed.feedback_prompted_at is not None


@pytest.mark.asyncio
async def test_mark_prompted_is_idempotent(test_client, async_session):
    user = await _create_user(async_session, "promptv")
    async with test_client as client:
        r1 = await client.post("/api/feedback/mark-prompted", headers=_auth_headers(user))
        assert r1.status_code == 204

        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == user.id))
            first = result.scalar_one().feedback_prompted_at
            assert first is not None

        r2 = await client.post("/api/feedback/mark-prompted", headers=_auth_headers(user))
        assert r2.status_code == 204

        async with async_session() as db:
            result = await db.execute(select(User).where(User.id == user.id))
            second = result.scalar_one().feedback_prompted_at
            assert second == first


@pytest.mark.asyncio
async def test_mark_prompted_requires_auth(test_client):
    async with test_client as client:
        r = await client.post("/api/feedback/mark-prompted")
        assert r.status_code in (401, 403)


@pytest.mark.asyncio
async def test_auth_me_exposes_feedback_prompted_at(test_client, async_session):
    user = await _create_user(async_session, "me_exposure")
    async with test_client as client:
        r = await client.get("/api/auth/me", headers=_auth_headers(user))
        assert r.status_code == 200
        assert r.json()["feedback_prompted_at"] is None

        r = await client.post("/api/feedback/mark-prompted", headers=_auth_headers(user))
        assert r.status_code == 204

        r = await client.get("/api/auth/me", headers=_auth_headers(user))
        assert r.status_code == 200
        assert r.json()["feedback_prompted_at"] is not None


async def _create_admin(async_session) -> User:
    async with async_session() as db:
        user = User(
            twitch_id="tw_admin",
            twitch_username="admin",
            twitch_display_name="Admin",
            api_token="tok_admin",
            role=UserRole.ADMIN,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_admin_feedback_list_requires_admin(test_client, async_session):
    user = await _create_user(async_session, "notadmin")
    async with test_client as client:
        r = await client.get("/api/admin/feedback", headers=_auth_headers(user))
        assert r.status_code == 403


@pytest.mark.asyncio
async def test_admin_feedback_list_basic(test_client, async_session):
    admin = await _create_admin(async_session)
    author = await _create_user(async_session, "author")
    async with async_session() as db:
        fb = Feedback(
            user_id=author.id,
            rating=4,
            comment="hey",
            source=FeedbackSource.USER_MENU,
            race_id=None,
            races_played_at_feedback=2,
        )
        db.add(fb)
        await db.commit()

    async with test_client as client:
        r = await client.get("/api/admin/feedback", headers=_auth_headers(admin))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert body["average_rating"] == 4.0
        assert body["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 1, "5": 0}
        assert len(body["items"]) == 1
        assert body["items"][0]["user"]["twitch_username"] == "author"
        assert body["items"][0]["race"] is None


@pytest.mark.asyncio
async def test_admin_feedback_filters(test_client, async_session):
    admin = await _create_admin(async_session)
    author = await _create_user(async_session, "f1")
    async with async_session() as db:
        for rating in (1, 3, 5):
            db.add(
                Feedback(
                    user_id=author.id,
                    rating=rating,
                    source=FeedbackSource.USER_MENU,
                    races_played_at_feedback=0,
                )
            )
        await db.commit()

    async with test_client as client:
        r = await client.get(
            "/api/admin/feedback?rating_min=4&rating_max=5",
            headers=_auth_headers(admin),
        )
        assert r.status_code == 200
        ratings = [it["rating"] for it in r.json()["items"]]
        assert ratings == [5]


@pytest.mark.asyncio
async def test_admin_feedback_filter_by_source(test_client, async_session):
    admin = await _create_admin(async_session)
    author = await _create_user(async_session, "src_filter_author")
    async with async_session() as db:
        # Create a race + participant so we can have a POST_FIRST_RACE feedback.
        race = Race(name="r_src", status=RaceStatus.FINISHED, organizer_id=author.id)
        db.add(race)
        await db.commit()
        await db.refresh(race)
        db.add(Participant(race_id=race.id, user_id=author.id, status=ParticipantStatus.FINISHED))
        db.add(
            Feedback(
                user_id=author.id,
                rating=3,
                source=FeedbackSource.USER_MENU,
                races_played_at_feedback=1,
            )
        )
        db.add(
            Feedback(
                user_id=author.id,
                rating=5,
                source=FeedbackSource.POST_FIRST_RACE,
                race_id=race.id,
                races_played_at_feedback=1,
            )
        )
        await db.commit()

    async with test_client as client:
        r = await client.get(
            "/api/admin/feedback?source=user_menu",
            headers=_auth_headers(admin),
        )
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1
        assert body["items"][0]["source"] == "user_menu"


@pytest.mark.asyncio
async def test_admin_feedback_empty_state(test_client, async_session):
    admin = await _create_admin(async_session)
    async with test_client as client:
        r = await client.get("/api/admin/feedback", headers=_auth_headers(admin))
        assert r.status_code == 200
        body = r.json()
        assert body["total"] == 0
        assert body["items"] == []
        assert body["average_rating"] is None
        assert body["distribution"] == {"1": 0, "2": 0, "3": 0, "4": 0, "5": 0}
