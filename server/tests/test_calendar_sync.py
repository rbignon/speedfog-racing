"""Tests for the cross-provider calendar_sync orchestration service."""

import contextlib
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Participant, Race, RaceStatus, Seed, SeedStatus, User, UserRole


@pytest.fixture
async def async_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    yield maker
    await engine.dispose()


async def _make_race(maker, *, organizer_participates=False, **overrides):
    async with maker() as db:
        user = User(
            twitch_id=f"cs-{uuid4().hex[:8]}",
            twitch_username="csorg",
            twitch_display_name="CsOrg",
            api_token=f"cs-token-{uuid4().hex[:8]}",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        seed = Seed(
            seed_number=f"cs-seed-{uuid4().hex[:8]}",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": {}},
            total_layers=5,
            folder_path="/fake",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.flush()
        fields = dict(
            name="Sync Race",
            organizer_id=user.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
            scheduled_at=datetime.now(UTC) + timedelta(hours=2),
        )
        fields.update(overrides)
        race = Race(**fields)
        db.add(race)
        await db.flush()
        if organizer_participates:
            db.add(Participant(race_id=race.id, user_id=user.id, color_index=0))
        await db.commit()
        await db.refresh(race)
        return race.id


@contextlib.contextmanager
def _patch_providers(maker):
    """Patch both provider wrappers plus the module's session maker.

    Yields ``(session_maker, create_discord, create_malenia, update_discord,
    update_malenia, delete_discord, delete_malenia)``.
    """
    cs = "speedfog_racing.services.calendar_sync"
    with (
        patch(f"{cs}.async_session_maker", maker) as m_session,
        patch(f"{cs}.create_scheduled_event", new_callable=AsyncMock) as m_cd,
        patch(f"{cs}.create_calendar_event", new_callable=AsyncMock) as m_cm,
        patch(f"{cs}.update_scheduled_event", new_callable=AsyncMock) as m_ud,
        patch(f"{cs}.update_calendar_event", new_callable=AsyncMock) as m_um,
        patch(f"{cs}.delete_scheduled_event", new_callable=AsyncMock) as m_dd,
        patch(f"{cs}.delete_calendar_event", new_callable=AsyncMock) as m_dm,
    ):
        yield (m_session, m_cd, m_cm, m_ud, m_um, m_dd, m_dm)


@pytest.mark.asyncio
async def test_create_public_scheduled_creates_both_and_persists(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session)
    with _patch_providers(async_session) as (_m, mc_d, mc_m, _u1, _u2, _d1, _d2):
        mc_d.return_value = "discord-id"
        mc_m.return_value = "malenia-id"
        await calendar_sync.create_calendar_events(race_id)
        mc_d.assert_called_once()
        mc_m.assert_called_once()

    async with async_session() as db:
        race = await db.get(Race, race_id)
        assert race.discord_event_id == "discord-id"
        assert race.malenia_event_id == "malenia-id"


@pytest.mark.asyncio
async def test_create_skips_private_race(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session, is_public=False)
    with _patch_providers(async_session) as (_m, mc_d, mc_m, *_):
        await calendar_sync.create_calendar_events(race_id)
        mc_d.assert_not_called()
        mc_m.assert_not_called()


@pytest.mark.asyncio
async def test_update_reschedule_patches_both(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session, discord_event_id="d1", malenia_event_id="m1")
    with _patch_providers(async_session) as (_m, _c1, _c2, mu_d, mu_m, *_):
        await calendar_sync.update_calendar_events(
            race_id, scheduled_changed=True, metadata_changed=False
        )
        mu_d.assert_called_once()
        mu_m.assert_called_once()


@pytest.mark.asyncio
async def test_update_metadata_patches_only_malenia(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session, discord_event_id="d1", malenia_event_id="m1")
    with _patch_providers(async_session) as (_m, _c1, _c2, mu_d, mu_m, *_):
        await calendar_sync.update_calendar_events(
            race_id, scheduled_changed=False, metadata_changed=True
        )
        mu_d.assert_not_called()
        mu_m.assert_called_once()
        assert mu_m.call_args[1]["race_name"] == "Sync Race"


@pytest.mark.asyncio
async def test_update_unqualified_deletes_and_clears(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(
        async_session, is_public=False, discord_event_id="d1", malenia_event_id="m1"
    )
    with _patch_providers(async_session) as (_m, _c1, _c2, _u1, _u2, md_d, md_m):
        await calendar_sync.update_calendar_events(
            race_id, scheduled_changed=False, metadata_changed=False
        )
        md_d.assert_called_once_with("d1")
        md_m.assert_called_once_with("m1")

    async with async_session() as db:
        race = await db.get(Race, race_id)
        assert race.discord_event_id is None
        assert race.malenia_event_id is None


@pytest.mark.asyncio
async def test_update_newly_qualified_creates(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session)  # public + scheduled, no ids yet
    with _patch_providers(async_session) as (_m, mc_d, mc_m, *_):
        mc_d.return_value = "d-new"
        mc_m.return_value = "m-new"
        await calendar_sync.update_calendar_events(
            race_id, scheduled_changed=True, metadata_changed=False
        )
        mc_d.assert_called_once()
        mc_m.assert_called_once()


@pytest.mark.asyncio
async def test_delete_calls_both_wrappers(async_session):
    from speedfog_racing.services import calendar_sync

    with _patch_providers(async_session) as (_m, _c1, _c2, _u1, _u2, md_d, md_m):
        await calendar_sync.delete_calendar_events(discord_event_id="d1", malenia_event_id="m1")
        md_d.assert_called_once_with("d1")
        md_m.assert_called_once_with("m1")


@pytest.mark.asyncio
async def test_add_calendar_participant_calls_wrapper(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session, malenia_event_id="m1")
    with (
        patch("speedfog_racing.services.calendar_sync.async_session_maker", async_session),
        patch(
            "speedfog_racing.services.calendar_sync.add_event_participant", new_callable=AsyncMock
        ) as mock_add,
    ):
        await calendar_sync.add_calendar_participant(race_id, "runner")
        mock_add.assert_awaited_once_with("m1", "runner")


@pytest.mark.asyncio
async def test_add_calendar_participant_skips_without_event(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session)  # no malenia_event_id
    with (
        patch("speedfog_racing.services.calendar_sync.async_session_maker", async_session),
        patch(
            "speedfog_racing.services.calendar_sync.add_event_participant", new_callable=AsyncMock
        ) as mock_add,
    ):
        await calendar_sync.add_calendar_participant(race_id, "runner")
        mock_add.assert_not_awaited()


@pytest.mark.asyncio
async def test_remove_calendar_participant_calls_wrapper(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session, malenia_event_id="m1")
    with (
        patch("speedfog_racing.services.calendar_sync.async_session_maker", async_session),
        patch(
            "speedfog_racing.services.calendar_sync.remove_event_participant_by_login",
            new_callable=AsyncMock,
        ) as mock_remove,
    ):
        await calendar_sync.remove_calendar_participant(race_id, "runner")
        mock_remove.assert_awaited_once_with("m1", "runner")


@pytest.mark.asyncio
async def test_create_seeds_participants(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session, organizer_participates=True)
    with (
        _patch_providers(async_session) as (_m, mc_d, mc_m, *_),
        patch(
            "speedfog_racing.services.calendar_sync.add_event_participant", new_callable=AsyncMock
        ) as mock_add,
    ):
        mc_d.return_value = "discord-id"
        mc_m.return_value = "malenia-id"
        await calendar_sync.create_calendar_events(race_id)
        mock_add.assert_awaited_once_with("malenia-id", "csorg")


@pytest.mark.asyncio
async def test_create_seeds_nothing_without_participants(async_session):
    from speedfog_racing.services import calendar_sync

    race_id = await _make_race(async_session)  # organizer does not participate
    with (
        _patch_providers(async_session) as (_m, mc_d, mc_m, *_),
        patch(
            "speedfog_racing.services.calendar_sync.add_event_participant", new_callable=AsyncMock
        ) as mock_add,
    ):
        # AsyncMock() would otherwise return a truthy auto-Mock, which fails to bind
        # as discord_event_id when committed to the DB.
        mc_d.return_value = None
        mc_m.return_value = "malenia-id"
        await calendar_sync.create_calendar_events(race_id)
        mock_add.assert_not_awaited()
