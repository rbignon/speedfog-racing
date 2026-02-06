"""Tests for user search endpoint."""

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import User, UserRole


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
async def auth_user(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="searcher",
            twitch_username="searcher",
            twitch_display_name="The Searcher",
            api_token="search_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def sample_users(async_session):
    async with async_session() as db:
        users = [
            User(
                twitch_id=f"u{i}",
                twitch_username=name,
                twitch_display_name=display,
                api_token=f"token_{i}",
            )
            for i, (name, display) in enumerate(
                [
                    ("alice", "Alice"),
                    ("alice_streams", "Alice Streams"),
                    ("bob", "Bob"),
                    ("charlie", "Charlie"),
                    ("ALICEupper", "ALICE Upper"),
                ]
            )
        ]
        db.add_all(users)
        await db.commit()
        for u in users:
            await db.refresh(u)
        return users


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


@pytest.mark.asyncio
async def test_search_requires_auth(test_client):
    async with test_client as client:
        response = await client.get("/api/users/search?q=alice")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_search_prefix_match(test_client, auth_user, sample_users):
    async with test_client as client:
        response = await client.get(
            "/api/users/search?q=alice",
            headers={"Authorization": f"Bearer {auth_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        usernames = {u["twitch_username"] for u in data}
        assert "alice" in usernames
        assert "alice_streams" in usernames
        assert "bob" not in usernames


@pytest.mark.asyncio
async def test_search_case_insensitive(test_client, auth_user, sample_users):
    async with test_client as client:
        response = await client.get(
            "/api/users/search?q=ALICE",
            headers={"Authorization": f"Bearer {auth_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        usernames = {u["twitch_username"] for u in data}
        # Should find alice, alice_streams, ALICEupper (all start with alice)
        assert "alice" in usernames
        assert "alice_streams" in usernames
        assert "ALICEupper" in usernames


@pytest.mark.asyncio
async def test_search_max_10_results(test_client, auth_user, async_session):
    """Search returns at most 10 results."""
    async with async_session() as db:
        for i in range(15):
            db.add(
                User(
                    twitch_id=f"many{i}",
                    twitch_username=f"many_user_{i:02d}",
                    twitch_display_name=f"Many User {i}",
                    api_token=f"many_token_{i}",
                )
            )
        await db.commit()

    async with test_client as client:
        response = await client.get(
            "/api/users/search?q=many",
            headers={"Authorization": f"Bearer {auth_user.api_token}"},
        )
        assert response.status_code == 200
        assert len(response.json()) == 10


@pytest.mark.asyncio
async def test_search_by_display_name(test_client, auth_user, sample_users):
    """Search matches display name prefix too."""
    async with test_client as client:
        response = await client.get(
            "/api/users/search?q=Charlie",
            headers={"Authorization": f"Bearer {auth_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["twitch_username"] == "charlie"


@pytest.mark.asyncio
async def test_search_no_results(test_client, auth_user, sample_users):
    async with test_client as client:
        response = await client.get(
            "/api/users/search?q=zzzzzzz",
            headers={"Authorization": f"Bearer {auth_user.api_token}"},
        )
        assert response.status_code == 200
        assert response.json() == []


@pytest.mark.asyncio
async def test_search_empty_query_rejected(test_client, auth_user):
    async with test_client as client:
        response = await client.get(
            "/api/users/search?q=",
            headers={"Authorization": f"Bearer {auth_user.api_token}"},
        )
        assert response.status_code == 422
