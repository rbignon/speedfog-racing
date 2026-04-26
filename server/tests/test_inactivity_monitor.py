"""Tests for inactivity monitor."""

import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    ChatChannel,
    ChatMessage,
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.inactivity_monitor import (
    abandon_inactive_participants,
    inactivity_monitor_loop,
)


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
    """Participant with stale IGT (>30min) is marked ABANDONED."""
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
            started_at=datetime.now(UTC) - timedelta(minutes=45),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            igt_ms=100000,
            last_igt_change_at=datetime.now(UTC) - timedelta(minutes=36),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids, abandoned_pids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 1
    assert p_id in abandoned_pids

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
            started_at=datetime.now(UTC) - timedelta(minutes=35),
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=noshow_status,
            igt_ms=0,
            last_igt_change_at=None,
            created_at=datetime.now(UTC) - timedelta(minutes=35),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids, abandoned_pids = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 1
    assert p_id in abandoned_pids

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
            started_at=datetime.now(UTC) - timedelta(minutes=20),
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

    abandoned_race_ids, _ = await abandon_inactive_participants(async_session)
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

    abandoned_race_ids, _ = await abandon_inactive_participants(async_session)
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

    abandoned_race_ids, _ = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.PLAYING


@pytest.mark.asyncio
async def test_does_not_abandon_late_joiner_within_window(async_session):
    """A late-joiner whose own created_at is recent must not be abandoned even
    if Race.started_at is older than the inactivity timeout."""
    async with async_session() as db:
        user = User(
            twitch_id="latejoin1",
            twitch_username="latejoin_player",
            api_token="latejoin_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_latejoin",
            twitch_username="org_latejoin",
            api_token="org_latejoin_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_latejoin",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/latejoin",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Late Join Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=45),
            late_join_window_minutes=60,
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.REGISTERED,
            igt_ms=0,
            last_igt_change_at=None,
            created_at=datetime.now(UTC) - timedelta(minutes=2),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids, _ = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.REGISTERED


@pytest.mark.asyncio
async def test_does_not_abandon_early_registrant_at_race_start(async_session):
    """A participant who registered well before the race started must not be
    abandoned the moment the race starts (the cutoff is per-participant, but
    capped by Race.started_at)."""
    async with async_session() as db:
        user = User(
            twitch_id="early1",
            twitch_username="early_player",
            api_token="early_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_early",
            twitch_username="org_early",
            api_token="org_early_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_early",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/early",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Early Registrant Race",
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
            created_at=datetime.now(UTC) - timedelta(hours=2),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids, _ = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.REGISTERED


@pytest.mark.asyncio
async def test_skips_noshow_when_race_duration_set(async_session):
    """When race_duration_minutes is set, the no-show branch is skipped:
    hard_close_loop will sweep non-terminal participants at the deadline."""
    async with async_session() as db:
        user = User(
            twitch_id="hcnoshow1",
            twitch_username="hcnoshow_player",
            api_token="hcnoshow_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_hcnoshow",
            twitch_username="org_hcnoshow",
            api_token="org_hcnoshow_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_hcnoshow",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/hcnoshow",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="HC No-Show Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=45),
            race_duration_minutes=240,
        )
        db.add(race)
        await db.flush()

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.REGISTERED,
            igt_ms=0,
            last_igt_change_at=None,
            created_at=datetime.now(UTC) - timedelta(minutes=45),
        )
        db.add(p)
        await db.commit()
        p_id = p.id

    abandoned_race_ids, _ = await abandon_inactive_participants(async_session)
    assert len(abandoned_race_ids) == 0

    async with async_session() as db:
        p = await db.get(Participant, p_id)
        assert p.status == ParticipantStatus.REGISTERED


@pytest.mark.asyncio
async def test_loop_persists_system_messages_when_no_room(async_session):
    """The loop persists inactivity + race-finished system messages even when no
    WebSocket room exists (they will replay via chat_history on reconnect).
    """
    async with async_session() as db:
        user = User(
            twitch_id="loop1",
            twitch_username="loop_player",
            twitch_display_name="Loop Player",
            api_token="loop_tok",
            role=UserRole.USER,
        )
        organizer = User(
            twitch_id="org_loop",
            twitch_username="org_loop",
            api_token="org_loop_tok",
            role=UserRole.ORGANIZER,
        )
        db.add_all([user, organizer])
        await db.flush()

        seed = Seed(
            seed_number="s_loop",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/loop",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name="Loop Race",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=datetime.now(UTC) - timedelta(minutes=45),
        )
        db.add(race)
        await db.flush()
        race_id = race.id

        p = Participant(
            race_id=race.id,
            user_id=user.id,
            status=ParticipantStatus.PLAYING,
            igt_ms=100000,
            last_igt_change_at=datetime.now(UTC) - timedelta(minutes=36),
        )
        db.add(p)
        await db.commit()

    task = asyncio.create_task(inactivity_monitor_loop(async_session))
    try:
        for _ in range(40):
            await asyncio.sleep(0.05)
            async with async_session() as db:
                result = await db.execute(
                    select(ChatMessage).where(
                        ChatMessage.race_id == race_id,
                        ChatMessage.message == "The race has finished.",
                    )
                )
                if len(result.scalars().all()) >= 1:
                    break
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async with async_session() as db:
        result = await db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id))
        messages = result.scalars().all()

        finished_msgs = [m for m in messages if m.message == "The race has finished."]
        finished_channels = {m.channel for m in finished_msgs}
        assert finished_channels == {ChatChannel.PUBLIC}

        inactive_msgs = [
            m
            for m in messages
            if m.message == "Loop Player has abandoned the race due to inactivity."
        ]
        assert len(inactive_msgs) == 1
        assert inactive_msgs[0].channel == ChatChannel.PUBLIC

        race = await db.get(Race, race_id)
        assert race is not None
        assert race.status == RaceStatus.FINISHED
