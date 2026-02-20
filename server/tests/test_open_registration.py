"""Tests for open registration (self-join / self-leave) feature."""

import pytest
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
            twitch_id="org_open",
            twitch_username="organizer_open",
            twitch_display_name="Organizer",
            api_token="org_open_token",
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
            twitch_id="player_open",
            twitch_username="player_open",
            twitch_display_name="Player",
            api_token="player_open_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def player2(async_session):
    async with async_session() as db:
        user = User(
            twitch_id="player2_open",
            twitch_username="player2_open",
            twitch_display_name="Player 2",
            api_token="player2_open_token",
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
            seed_number="open_reg_seed",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/open_reg_seed.zip",
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


async def _create_open_race(client, token, max_participants=4):
    """Helper to create an open registration race."""
    response = await client.post(
        "/api/races",
        json={
            "name": "Open Race",
            "pool_name": "standard",
            "open_registration": True,
            "max_participants": max_participants,
        },
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 201
    return response.json()


# =============================================================================
# Creation Tests
# =============================================================================


@pytest.mark.asyncio
async def test_create_race_open_registration(test_client, organizer, seed):
    """Creating an open registration race succeeds."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)
        assert race["open_registration"] is True
        assert race["max_participants"] == 4


@pytest.mark.asyncio
async def test_create_race_open_without_max(test_client, organizer, seed):
    """Creating open registration without max_participants fails."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={
                "name": "Bad Race",
                "pool_name": "standard",
                "open_registration": True,
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_race_open_with_low_max(test_client, organizer, seed):
    """Creating open registration with max_participants < 2 fails."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={
                "name": "Bad Race",
                "pool_name": "standard",
                "open_registration": True,
                "max_participants": 1,
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 422


@pytest.mark.asyncio
async def test_create_closed_race_default(test_client, organizer, seed):
    """Races default to closed registration."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Normal Race", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        assert response.json()["open_registration"] is False
        assert response.json()["max_participants"] is None


# =============================================================================
# Join Tests
# =============================================================================


@pytest.mark.asyncio
async def test_join_open_race(test_client, organizer, player, seed):
    """Authenticated user can join an open race."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["user"]["twitch_username"] == "player_open"
        assert data["color_index"] == 0


@pytest.mark.asyncio
async def test_join_closed_race(test_client, organizer, player, seed):
    """Cannot join an invite-only race."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={"name": "Closed Race", "pool_name": "standard"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        race = response.json()

        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 403
        assert "open registration" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_multiple_players_join(test_client, organizer, player, player2, seed):
    """Multiple players can join an open race."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token, max_participants=4)

        # Player 1 joins
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200
        assert response.json()["color_index"] == 0

        # Player 2 joins
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player2.api_token}"},
        )
        assert response.status_code == 200
        assert response.json()["color_index"] == 1


@pytest.mark.asyncio
async def test_join_full_race_at_capacity(
    test_client, organizer, player, player2, async_session, seed
):
    """Cannot join when race has reached max_participants."""
    async with test_client as client:
        # Create race with max 2, organizer participates (takes 1 slot)
        response = await client.post(
            "/api/races",
            json={
                "name": "Full Race",
                "pool_name": "standard",
                "open_registration": True,
                "max_participants": 2,
                "organizer_participates": True,
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        race = response.json()

        # Player 1 joins — fills the race (organizer + player1 = 2)
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200

        # Player 2 tries to join — should fail (full)
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player2.api_token}"},
        )
        assert response.status_code == 409
        assert "full" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_join_already_participant(test_client, organizer, player, seed):
    """Cannot join if already a participant."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)

        # Join once
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200

        # Try joining again
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 409
        assert "already" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_join_as_caster(test_client, organizer, player, seed):
    """Cannot join if already a caster."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)

        # Add player as caster
        response = await client.post(
            f"/api/races/{race['id']}/casters",
            json={"twitch_username": "player_open"},
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201

        # Try to join as participant
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 409
        assert "caster" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_join_running_race(test_client, organizer, player, seed, async_session):
    """Cannot join a race that has started."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)

        # Manually set race to RUNNING
        async with async_session() as db:
            from sqlalchemy import update

            await db.execute(
                update(Race).where(Race.name == "Open Race").values(status=RaceStatus.RUNNING)
            )
            await db.commit()

        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 400
        assert "setup" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_join_requires_auth(test_client, organizer, seed):
    """Cannot join without authentication."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)

        response = await client.post(f"/api/races/{race['id']}/join")
        assert response.status_code == 401


# =============================================================================
# Leave Tests
# =============================================================================


@pytest.mark.asyncio
async def test_leave_race(test_client, organizer, player, seed):
    """Participant can leave a race."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)

        # Join
        response = await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 200

        # Leave
        response = await client.post(
            f"/api/races/{race['id']}/leave",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 204

        # Verify participant is gone
        response = await client.get(
            f"/api/races/{race['id']}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        detail = response.json()
        usernames = [p["user"]["twitch_username"] for p in detail["participants"]]
        assert "player_open" not in usernames


@pytest.mark.asyncio
async def test_leave_as_organizer(test_client, organizer, seed):
    """Organizer cannot leave their own race."""
    async with test_client as client:
        response = await client.post(
            "/api/races",
            json={
                "name": "Org Race",
                "pool_name": "standard",
                "open_registration": True,
                "max_participants": 4,
                "organizer_participates": True,
            },
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 201
        race = response.json()

        response = await client.post(
            f"/api/races/{race['id']}/leave",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 403
        assert "organizer" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_leave_not_participant(test_client, organizer, player, seed):
    """Cannot leave if not a participant."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)

        response = await client.post(
            f"/api/races/{race['id']}/leave",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_leave_running_race(test_client, organizer, player, seed, async_session):
    """Cannot leave a running race."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token)

        # Join
        await client.post(
            f"/api/races/{race['id']}/join",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )

        # Set race to RUNNING
        async with async_session() as db:
            from sqlalchemy import update

            await db.execute(
                update(Race).where(Race.name == "Open Race").values(status=RaceStatus.RUNNING)
            )
            await db.commit()

        response = await client.post(
            f"/api/races/{race['id']}/leave",
            headers={"Authorization": f"Bearer {player.api_token}"},
        )
        assert response.status_code == 400


# =============================================================================
# Response Fields Tests
# =============================================================================


@pytest.mark.asyncio
async def test_race_detail_includes_open_registration(test_client, organizer, seed):
    """Race detail response includes open_registration and max_participants."""
    async with test_client as client:
        race = await _create_open_race(client, organizer.api_token, max_participants=8)

        response = await client.get(
            f"/api/races/{race['id']}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        detail = response.json()
        assert detail["open_registration"] is True
        assert detail["max_participants"] == 8


@pytest.mark.asyncio
async def test_race_list_includes_open_registration(test_client, organizer, seed):
    """Race list response includes open_registration and max_participants."""
    async with test_client as client:
        await _create_open_race(client, organizer.api_token)

        response = await client.get("/api/races")
        assert response.status_code == 200
        races = response.json()["races"]
        assert len(races) > 0
        race = next(r for r in races if r["name"] == "Open Race")
        assert race["open_registration"] is True
        assert race["max_participants"] == 4
