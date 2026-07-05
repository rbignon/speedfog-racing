"""Test Discord scheduled event integration with race lifecycle."""

import asyncio
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import UUID, uuid4

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
async def test_create_race_syncs_calendar_event(test_client, organizer, seed):
    """Creating a public race with scheduled_at fires calendar_sync.create_calendar_events."""
    scheduled = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    with patch(
        "speedfog_racing.api.races.create_calendar_events", new_callable=AsyncMock
    ) as mock_sync:
        async with test_client as client:
            resp = await client.post(
                "/api/races",
                json={
                    "name": "Calendar Event Test",
                    "pool_name": "standard",
                    "is_public": True,
                    "scheduled_at": scheduled,
                },
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 201, resp.text
            await asyncio.sleep(0.1)
            mock_sync.assert_called_once()
            assert str(mock_sync.call_args[0][0]) == resp.json()["id"]


@pytest.mark.asyncio
async def test_create_race_no_event_when_private(test_client, organizer, seed):
    """Creating a private race should not create a Discord event."""
    scheduled = (datetime.now(UTC) + timedelta(hours=2)).isoformat()

    with patch(
        "speedfog_racing.api.races.create_calendar_events", new_callable=AsyncMock
    ) as mock_sync:
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
            mock_sync.assert_not_called()


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
        patch("speedfog_racing.api.races.create_calendar_events", new_callable=AsyncMock),
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
        patch("speedfog_racing.api.races.create_calendar_events", new_callable=AsyncMock),
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
        "speedfog_racing.api.races.delete_calendar_events", new_callable=AsyncMock
    ) as mock_delete:
        async with test_client as client:
            resp = await client.delete(
                f"/api/races/{race_id}",
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 204
            await asyncio.sleep(0.1)
            mock_delete.assert_called_once_with(
                discord_event_id="discord-event-to-delete", malenia_event_id=None
            )


# =============================================================================
# Race update -> calendar re-sync
# =============================================================================


@pytest.mark.asyncio
async def test_reschedule_calls_update_calendar_events(test_client, organizer, seed, async_session):
    """PATCHing scheduled_at re-syncs the calendar with scheduled_changed=True."""
    async with async_session() as db:
        race = Race(
            name="Reschedule Test",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
            scheduled_at=datetime.now(UTC) + timedelta(hours=2),
            discord_event_id="d1",
            malenia_event_id="m1",
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    new_time = (datetime.now(UTC) + timedelta(hours=5)).isoformat()
    with patch(
        "speedfog_racing.api.races.update_calendar_events", new_callable=AsyncMock
    ) as mock_update:
        async with test_client as client:
            resp = await client.patch(
                f"/api/races/{race_id}",
                json={"scheduled_at": new_time},
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 200, resp.text
            await asyncio.sleep(0.1)
            mock_update.assert_called_once()
            assert mock_update.call_args[1]["scheduled_changed"] is True
            assert mock_update.call_args[1]["metadata_changed"] is False


@pytest.mark.asyncio
async def test_edit_rules_calls_update_calendar_events(test_client, organizer, seed, async_session):
    """PATCHing custom_rules re-syncs the calendar with metadata_changed=True."""
    async with async_session() as db:
        race = Race(
            name="Rules Test",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
            scheduled_at=datetime.now(UTC) + timedelta(hours=2),
            discord_event_id="d1",
            malenia_event_id="m1",
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    with patch(
        "speedfog_racing.api.races.update_calendar_events", new_callable=AsyncMock
    ) as mock_update:
        async with test_client as client:
            resp = await client.patch(
                f"/api/races/{race_id}",
                json={"custom_rules": "No torrent"},
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 200, resp.text
            await asyncio.sleep(0.1)
            mock_update.assert_called_once()
            assert mock_update.call_args[1]["metadata_changed"] is True
            assert mock_update.call_args[1]["scheduled_changed"] is False


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


# =============================================================================
# Participant sync -> malenia
# =============================================================================


async def _make_second_user(async_session):
    from speedfog_racing.models import User

    async with async_session() as db:
        u = User(
            twitch_id=f"p2-{uuid4().hex[:8]}",
            twitch_username=f"racer_{uuid4().hex[:6]}",
            twitch_display_name="Racer",
            api_token=f"p2-token-{uuid4().hex[:8]}",
        )
        db.add(u)
        await db.commit()
        await db.refresh(u)
        return u


async def _make_public_scheduled_race(async_session, organizer, seed, **overrides):
    fields = dict(
        name="Participant Sync Race",
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=RaceStatus.SETUP,
        is_public=True,
        scheduled_at=datetime.now(UTC) + timedelta(hours=2),
    )
    fields.update(overrides)
    async with async_session() as db:
        race = Race(**fields)
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return str(race.id)


@pytest.mark.asyncio
async def test_join_syncs_calendar_participant(test_client, organizer, seed, async_session):
    second = await _make_second_user(async_session)
    race_id = await _make_public_scheduled_race(
        async_session, organizer, seed, open_registration=True, max_participants=8
    )
    with patch(
        "speedfog_racing.api.races.add_calendar_participant", new_callable=AsyncMock
    ) as mock_add:
        async with test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/join",
                headers={"Authorization": f"Bearer {second.api_token}"},
            )
            assert resp.status_code == 200, resp.text
            await asyncio.sleep(0.1)
            mock_add.assert_awaited_once_with(UUID(race_id), second.twitch_username)


@pytest.mark.asyncio
async def test_join_private_race_skips_participant_sync(
    test_client, organizer, seed, async_session
):
    second = await _make_second_user(async_session)
    race_id = await _make_public_scheduled_race(
        async_session, organizer, seed, is_public=False, open_registration=True, max_participants=8
    )
    with patch(
        "speedfog_racing.api.races.add_calendar_participant", new_callable=AsyncMock
    ) as mock_add:
        async with test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/join",
                headers={"Authorization": f"Bearer {second.api_token}"},
            )
            assert resp.status_code == 200, resp.text
            await asyncio.sleep(0.1)
            mock_add.assert_not_awaited()


@pytest.mark.asyncio
async def test_add_participant_syncs_calendar_participant(
    test_client, organizer, seed, async_session
):
    second = await _make_second_user(async_session)
    race_id = await _make_public_scheduled_race(async_session, organizer, seed)
    with patch(
        "speedfog_racing.api.races.add_calendar_participant", new_callable=AsyncMock
    ) as mock_add:
        async with test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/participants",
                json={"twitch_username": second.twitch_username},
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 200, resp.text
            await asyncio.sleep(0.1)
            mock_add.assert_awaited_once_with(UUID(race_id), second.twitch_username)


@pytest.mark.asyncio
async def test_leave_syncs_calendar_participant_removal(
    test_client, organizer, seed, async_session
):
    from speedfog_racing.models import Participant

    second = await _make_second_user(async_session)
    race_id = await _make_public_scheduled_race(async_session, organizer, seed)
    async with async_session() as db:
        db.add(Participant(race_id=UUID(race_id), user_id=second.id, color_index=1))
        await db.commit()
    with patch(
        "speedfog_racing.api.races.remove_calendar_participant", new_callable=AsyncMock
    ) as mock_remove:
        async with test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/leave",
                headers={"Authorization": f"Bearer {second.api_token}"},
            )
            assert resp.status_code == 204
            await asyncio.sleep(0.1)
            mock_remove.assert_awaited_once_with(UUID(race_id), second.twitch_username)


@pytest.mark.asyncio
async def test_remove_participant_syncs_calendar_removal(
    test_client, organizer, seed, async_session
):
    from speedfog_racing.models import Participant

    second = await _make_second_user(async_session)
    race_id = await _make_public_scheduled_race(async_session, organizer, seed)
    async with async_session() as db:
        p = Participant(race_id=UUID(race_id), user_id=second.id, color_index=1)
        db.add(p)
        await db.commit()
        await db.refresh(p)
        participant_id = str(p.id)
    with patch(
        "speedfog_racing.api.races.remove_calendar_participant", new_callable=AsyncMock
    ) as mock_remove:
        async with test_client as client:
            resp = await client.delete(
                f"/api/races/{race_id}/participants/{participant_id}",
                headers={"Authorization": f"Bearer {organizer.api_token}"},
            )
            assert resp.status_code == 204
            await asyncio.sleep(0.1)
            mock_remove.assert_awaited_once_with(UUID(race_id), second.twitch_username)
