"""Tests for inactivity monitor."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.inactivity_monitor import abandon_inactive_participants


@pytest.fixture
async def async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def async_session(async_engine):
    return async_sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.mark.asyncio
async def test_abandons_stale_participant(async_session):
    """Participant with stale IGT (>15min) is marked ABANDONED."""
    async with async_session() as db:
        user = User(
            twitch_id="stale1",
            twitch_username="stale_player",
            api_token="stale_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_stale",
            twitch_username="org_stale",
            api_token="org_stale_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_stale",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/stale",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Stale Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=30),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            igt_ms=100000,
            last_igt_change_at=datetime.now(UTC) - timedelta(minutes=16),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 1

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.ABANDONED


@pytest.mark.asyncio
@pytest.mark.parametrize("noshow_status", [ParticipantStatus.REGISTERED, ParticipantStatus.READY])
async def test_abandons_noshow_participant(async_session, noshow_status):
    """REGISTERED/READY participant who never started playing after timeout is ABANDONED."""
    async with async_session() as db:
        user = User(
            twitch_id="noshow1",
            twitch_username="noshow_player",
            api_token="noshow_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_noshow",
            twitch_username="org_noshow",
            api_token="org_noshow_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_noshow",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/noshow",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="No-Show Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=20),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=noshow_status,
            igt_ms=0,
            last_igt_change_at=None,
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 1

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.ABANDONED


@pytest.mark.asyncio
async def test_does_not_abandon_recent_noshow(async_session):
    """REGISTERED participant in a recently started race is NOT abandoned yet."""
    async with async_session() as db:
        user = User(
            twitch_id="recent1",
            twitch_username="recent_player",
            api_token="recent_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_recent",
            twitch_username="org_recent",
            api_token="org_recent_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_recent",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/recent",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Recent Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=5),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.REGISTERED,
            igt_ms=0,
            last_igt_change_at=None,
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.REGISTERED


@pytest.mark.asyncio
async def test_does_not_abandon_active_participant(async_session):
    """Participant with recent IGT change is not abandoned."""
    async with async_session() as db:
        user = User(
            twitch_id="active1",
            twitch_username="active_player",
            api_token="active_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_active",
            twitch_username="org_active",
            api_token="org_active_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_active",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/active",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Active Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            igt_ms=100000,
            last_igt_change_at=datetime.now(UTC) - timedelta(minutes=2),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.PLAYING


@pytest.mark.asyncio
async def test_does_not_abandon_null_last_igt(async_session):
    """Participant with NULL last_igt_change_at is not abandoned (still loading)."""
    async with async_session() as db:
        user = User(
            twitch_id="null1",
            twitch_username="null_player",
            api_token="null_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_null",
            twitch_username="org_null",
            api_token="org_null_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_null",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/null",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Null IGT Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            igt_ms=0,
            last_igt_change_at=None,
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.PLAYING
