"""Test Discord scheduled event integration with race lifecycle."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

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
            twitch_id=f"discord-org-{uuid4().hex[:8]}",
            twitch_username="discordorg",
            twitch_display_name="DiscordOrg",
            api_token=f"discord-org-token-{uuid4().hex[:8]}",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def seed(async_session):
    async with async_session() as db:
        s = Seed(
            seed_number=f"discord-seed-{uuid4().hex[:8]}",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/fake/path",
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


# =============================================================================
# Race creation → Discord event
# =============================================================================


@pytest.mark.asyncio
async def test_create_race_creates_discord_event(test_client, organizer, seed, async_session):
    """Creating a public race with scheduled_at should fire create_scheduled_event."""
    scheduled = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    with (
        patch(
            "speedfog_racing.api.races.create_scheduled_event", new_callable=AsyncMock
        ) as mock_create,
        # Also patch async_session_maker since the fire-and-forget task uses it
        patch("speedfog_racing.api.races.async_session_maker", async_session),
    ):
        mock_create.return_value = "discord-event-123"

        async with test_client as client:
            resp = await client.post(
                "/api/races",
                json={
                    "name": "Discord Event Test",
                    "pool_name": "standard",
                    "is_public": True,
                    "scheduled_at": scheduled,
                },
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )

            assert resp.status_code == 201, resp.text
            # Let fire-and-forget tasks complete
            await asyncio.sleep(0.1)
            mock_create.assert_called_once()
            assert mock_create.call_args[1]["race_name"] == "Discord Event Test"


@pytest.mark.asyncio
async def test_create_race_no_event_when_private(test_client, organizer, seed):
    """Creating a private race should not create a Discord event."""
    scheduled = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    with patch(
        "speedfog_racing.api.races.create_scheduled_event", new_callable=AsyncMock
    ) as mock_create:
        async with test_client as client:
            resp = await client.post(
                "/api/races",
                json={
                    "name": "Private Race Test",
                    "pool_name": "standard",
                    "is_public": False,
                    "scheduled_at": scheduled,
                },
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 201
            await asyncio.sleep(0.1)
            mock_create.assert_not_called()


# =============================================================================
# Race creation → Discord webhook notification
# =============================================================================


@pytest.mark.asyncio
async def test_create_public_open_race_sends_notification(test_client, organizer, seed):
    """A public race with open registration pings @Runner via notify_race_created."""
    scheduled = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    with (
        patch(
            "speedfog_racing.api.races.notify_race_created", new_callable=AsyncMock
        ) as mock_notify,
        patch("speedfog_racing.api.races.create_scheduled_event", new_callable=AsyncMock),
    ):
        async with test_client as client:
            resp = await client.post(
                "/api/races",
                json={
                    "name": "Public Open Race",
                    "pool_name": "standard",
                    "is_public": True,
                    "scheduled_at": scheduled,
                    "open_registration": True,
                    "max_participants": 8,
                },
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 201, resp.text
            await asyncio.sleep(0.1)
            mock_notify.assert_called_once()


@pytest.mark.asyncio
async def test_create_public_invite_only_race_skips_notification(test_client, organizer, seed):
    """A public but invite-only race does not ping @Runner: invitees join by link."""
    scheduled = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    with (
        patch(
            "speedfog_racing.api.races.notify_race_created", new_callable=AsyncMock
        ) as mock_notify,
        patch("speedfog_racing.api.races.create_scheduled_event", new_callable=AsyncMock),
    ):
        async with test_client as client:
            resp = await client.post(
                "/api/races",
                json={
                    "name": "Public Invite-Only Race",
                    "pool_name": "standard",
                    "is_public": True,
                    "scheduled_at": scheduled,
                    "open_registration": False,
                },
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 201, resp.text
            await asyncio.sleep(0.1)
            mock_notify.assert_not_called()


# =============================================================================
# Race deletion → Discord event deletion
# =============================================================================


@pytest.mark.asyncio
async def test_delete_race_deletes_discord_event(test_client, organizer, seed, async_session):
    """Deleting a race with discord_event_id should delete the Discord event."""
    # Create race directly in DB
    async with async_session() as db:
        race = Race(
            name="Delete Event Test",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
            discord_event_id="discord-event-to-delete",
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        race_id = str(race.id)

    with patch(
        "speedfog_racing.api.races.delete_scheduled_event", new_callable=AsyncMock
    ) as mock_delete:
        async with test_client as client:
            resp = await client.delete(
                f"/api/races/{race_id}",
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 204
            await asyncio.sleep(0.1)
            mock_delete.assert_called_once_with("discord-event-to-delete")


# =============================================================================
# Race start → event ACTIVE
# =============================================================================


@pytest.mark.asyncio
async def test_start_race_activates_discord_event(test_client, organizer, seed, async_session):
    """Starting a race with discord_event_id should set event status to ACTIVE."""
    from speedfog_racing.models import Participant

    # Create race with 2 participants directly in DB
    async with async_session() as db:
        second_user = User(
            twitch_id="discord-start-user2",
            twitch_username="discord_start_user2",
            twitch_display_name="User2",
            api_token="discord-start-token2",
        )
        db.add(second_user)
        await db.flush()

        race = Race(
            name="Start Event Test",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
            discord_event_id="discord-event-start",
            seeds_released_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=organizer.id, color_index=0))
        db.add(Participant(race_id=race.id, user_id=second_user.id, color_index=1))
        await db.commit()
        race_id = str(race.id)

    with patch("speedfog_racing.api.races.set_event_status", new_callable=AsyncMock) as mock_status:
        async with test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/start",
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 200, resp.text
            await asyncio.sleep(0.1)
            mock_status.assert_called_once_with("discord-event-start", 2)


# =============================================================================
# Race finish → event COMPLETED
# =============================================================================


@pytest.mark.asyncio
async def test_finish_race_completes_discord_event(test_client, organizer, seed, async_session):
    """Finishing a race with discord_event_id should set event status to COMPLETED."""
    from speedfog_racing.models import Participant

    # Create running race directly in DB
    async with async_session() as db:
        race = Race(
            name="Finish Event Test",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            discord_event_id="discord-event-finish",
            seeds_released_at=datetime.now(UTC),
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=organizer.id,
            color_index=0,
        )
        db.add(participant)
        await db.commit()
        race_id = str(race.id)

    with patch("speedfog_racing.discord.set_event_status", new_callable=AsyncMock) as mock_status:
        async with test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/finish",
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 200, resp.text
            await asyncio.sleep(0.1)
            mock_status.assert_called_once_with("discord-event-finish", 3)
