"""Test invite API endpoints."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Invite, Race, RaceStatus, Seed, SeedStatus, User, UserRole


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
async def organizer(async_session):
    """Create an organizer user."""
    async with async_session() as db:
        user = User(
            twitch_id="org123",
            twitch_username="organizer",
            twitch_display_name="The Organizer",
            api_token="organizer_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def invited_user(async_session):
    """Create a user who will accept an invite."""
    async with async_session() as db:
        user = User(
            twitch_id="inv123",
            twitch_username="invited_player",
            twitch_display_name="Invited Player",
            api_token="invited_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def race_with_invite(async_session, organizer):
    """Create a race with a pending invite."""
    async with async_session() as db:
        # Create seed
        seed = Seed(
            seed_number=999,
            pool_name="standard",
            graph_json={"total_layers": 10},
            total_layers=10,
            folder_path="/test/seed_999",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        # Create race
        race = Race(
            name="Invite Test Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.DRAFT,
        )
        db.add(race)
        await db.flush()

        # Create invite
        invite = Invite(
            race_id=race.id,
            twitch_username="invited_player",
            token="test_invite_token",
        )
        db.add(invite)
        await db.commit()

        return {"race": race, "invite": invite, "seed": seed}


@pytest.fixture
def test_client(async_session):
    """Create test client with async database override."""
    from httpx import ASGITransport, AsyncClient

    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


# =============================================================================
# Invite Info Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_invite_info(test_client, race_with_invite):
    """Getting invite info returns public race details."""
    async with test_client as client:
        response = await client.get("/api/invite/test_invite_token")
        assert response.status_code == 200
        data = response.json()
        assert data["race_name"] == "Invite Test Race"
        assert data["organizer_name"] == "The Organizer"
        assert data["twitch_username"] == "invited_player"
        assert data["race_status"] == "draft"


@pytest.mark.asyncio
async def test_get_invite_not_found(test_client):
    """Getting a nonexistent invite returns 404."""
    async with test_client as client:
        response = await client.get("/api/invite/nonexistent_token")
        assert response.status_code == 404


# =============================================================================
# Accept Invite Tests
# =============================================================================


@pytest.mark.asyncio
async def test_accept_invite_requires_auth(test_client, race_with_invite):
    """Accepting an invite requires authentication."""
    async with test_client as client:
        response = await client.post("/api/invite/test_invite_token/accept")
        assert response.status_code == 401


@pytest.mark.asyncio
async def test_accept_invite_success(test_client, race_with_invite, invited_user):
    """Accepting an invite creates a participant."""
    async with test_client as client:
        response = await client.post(
            "/api/invite/test_invite_token/accept",
            headers={"Authorization": f"Bearer {invited_user.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["participant"]["user"]["twitch_username"] == "invited_player"
        assert data["race_id"] == str(race_with_invite["race"].id)


@pytest.mark.asyncio
async def test_accept_invite_wrong_user(test_client, race_with_invite, organizer):
    """Cannot accept an invite meant for someone else."""
    async with test_client as client:
        response = await client.post(
            "/api/invite/test_invite_token/accept",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 403
        assert "not for your account" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_cannot_accept_invite_twice(test_client, race_with_invite, invited_user):
    """Cannot accept an invite that's already been accepted."""
    async with test_client as client:
        # Accept once
        await client.post(
            "/api/invite/test_invite_token/accept",
            headers={"Authorization": f"Bearer {invited_user.api_token}"},
        )

        # Try to accept again
        response = await client.post(
            "/api/invite/test_invite_token/accept",
            headers={"Authorization": f"Bearer {invited_user.api_token}"},
        )
        assert response.status_code == 400
        assert "already been accepted" in response.json()["detail"]


@pytest.mark.asyncio
async def test_cannot_accept_invite_for_started_race(
    test_client, async_session, race_with_invite, invited_user
):
    """Cannot accept an invite for a race that has started."""
    # Update race status to running
    async with async_session() as db:
        race = race_with_invite["race"]
        race.status = RaceStatus.RUNNING
        db.add(race)
        await db.commit()

    async with test_client as client:
        response = await client.post(
            "/api/invite/test_invite_token/accept",
            headers={"Authorization": f"Bearer {invited_user.api_token}"},
        )
        assert response.status_code == 400
        assert "already started" in response.json()["detail"]


# =============================================================================
# Pending Invite Visibility Tests
# =============================================================================


@pytest.fixture
async def non_organizer(async_session):
    """Create a non-organizer user."""
    async with async_session() as db:
        user = User(
            twitch_id="other123",
            twitch_username="other_user",
            twitch_display_name="Other User",
            api_token="other_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.mark.asyncio
async def test_race_detail_includes_pending_invites(test_client, race_with_invite, organizer):
    """GET race detail includes pending invites."""
    race = race_with_invite["race"]
    async with test_client as client:
        response = await client.get(
            f"/api/races/{race.id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert "pending_invites" in data
        assert len(data["pending_invites"]) == 1
        inv = data["pending_invites"][0]
        assert inv["twitch_username"] == "invited_player"
        assert "id" in inv
        assert "created_at" in inv
        # Token must NOT be exposed
        assert "token" not in inv


@pytest.mark.asyncio
async def test_race_detail_excludes_accepted_invites(
    test_client, async_session, race_with_invite, organizer, invited_user
):
    """Accepted invites are not shown in pending_invites."""
    race = race_with_invite["race"]
    invite = race_with_invite["invite"]

    # Mark invite as accepted
    async with async_session() as db:
        invite.accepted = True
        db.add(invite)
        await db.commit()

    async with test_client as client:
        response = await client.get(
            f"/api/races/{race.id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 200
        data = response.json()
        assert len(data["pending_invites"]) == 0


# =============================================================================
# Revoke Invite Tests
# =============================================================================


@pytest.mark.asyncio
async def test_revoke_invite_success(test_client, race_with_invite, organizer):
    """Organizer can revoke a pending invite."""
    race = race_with_invite["race"]
    invite = race_with_invite["invite"]
    async with test_client as client:
        response = await client.delete(
            f"/api/races/{race.id}/invites/{invite.id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 204

        # Verify invite is gone from race detail
        detail = await client.get(
            f"/api/races/{race.id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert len(detail.json()["pending_invites"]) == 0


@pytest.mark.asyncio
async def test_revoke_invite_non_organizer_forbidden(test_client, race_with_invite, non_organizer):
    """Non-organizer cannot revoke invites."""
    race = race_with_invite["race"]
    invite = race_with_invite["invite"]
    async with test_client as client:
        response = await client.delete(
            f"/api/races/{race.id}/invites/{invite.id}",
            headers={"Authorization": f"Bearer {non_organizer.api_token}"},
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_revoke_invite_started_race_rejected(
    test_client, async_session, race_with_invite, organizer
):
    """Cannot revoke invites on a started race."""
    race = race_with_invite["race"]
    invite = race_with_invite["invite"]

    async with async_session() as db:
        race.status = RaceStatus.RUNNING
        db.add(race)
        await db.commit()

    async with test_client as client:
        response = await client.delete(
            f"/api/races/{race.id}/invites/{invite.id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400


@pytest.mark.asyncio
async def test_revoke_invite_not_found(test_client, race_with_invite, organizer):
    """Revoking a nonexistent invite returns 404."""
    race = race_with_invite["race"]
    fake_id = uuid.uuid4()
    async with test_client as client:
        response = await client.delete(
            f"/api/races/{race.id}/invites/{fake_id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 404


@pytest.mark.asyncio
async def test_revoke_accepted_invite_rejected(
    test_client, async_session, race_with_invite, organizer
):
    """Cannot revoke an invite that has already been accepted."""
    race = race_with_invite["race"]
    invite = race_with_invite["invite"]

    async with async_session() as db:
        invite.accepted = True
        db.add(invite)
        await db.commit()

    async with test_client as client:
        response = await client.delete(
            f"/api/races/{race.id}/invites/{invite.id}",
            headers={"Authorization": f"Bearer {organizer.api_token}"},
        )
        assert response.status_code == 400
        assert "accepted" in response.json()["detail"].lower()
