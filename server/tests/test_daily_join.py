"""HTTP tests for self-join behavior on a running Daily Seed."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

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


@pytest.fixture
async def dj_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def dj_async_session_maker(dj_async_engine):
    return async_sessionmaker(dj_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def dj_test_client(dj_async_session_maker):
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.database import get_db
    from speedfog_racing.main import app

    async def override_get_db():
        async with dj_async_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _seed_running_daily(session_maker) -> tuple[Race, str]:
    """Insert a running Daily Seed plus a player; return (race, player api_token).

    started_at is anchored a few hours before "now" so the 24h late-join
    window stays open whenever the test happens to run.
    """
    started = datetime.now(UTC) - timedelta(hours=2)
    today = started.date()
    async with session_maker() as db:
        sys_user = User(
            twitch_id="sys-dj",
            twitch_username="sys_dj",
            twitch_display_name="System",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        player = User(
            twitch_id="player-dj",
            twitch_username="player_dj",
            twitch_display_name="Player",
            api_token=f"tok-{uuid4().hex[:8]}",
            role=UserRole.USER,
        )
        db.add_all([sys_user, player])
        await db.flush()

        seed = Seed(
            seed_number="dj-seed",
            pool_name="standard",
            graph_json={"nodes": {}, "total_layers": 5},
            total_layers=5,
            folder_path="/test/dj-seed",
            status=SeedStatus.CONSUMED,
        )
        db.add(seed)
        await db.flush()

        race = Race(
            name=f"Daily Seed - {today.isoformat()}",
            organizer_id=sys_user.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            open_registration=True,
            daily_date=today,
            exclude_from_stats=True,
            started_at=started,
            seeds_released_at=started,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return race, player.api_token


@pytest.mark.asyncio
async def test_non_participant_can_join_running_daily(
    dj_test_client, dj_async_session_maker
) -> None:
    race, token = await _seed_running_daily(dj_async_session_maker)
    response = await dj_test_client.post(
        f"/api/races/{race.id}/join",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text
    assert response.json()["status"] == ParticipantStatus.REGISTERED.value


@pytest.mark.asyncio
async def test_daily_participant_cannot_rejoin(dj_test_client, dj_async_session_maker) -> None:
    race, token = await _seed_running_daily(dj_async_session_maker)
    first = await dj_test_client.post(
        f"/api/races/{race.id}/join",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert first.status_code == 200
    second = await dj_test_client.post(
        f"/api/races/{race.id}/join",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_daily_join_rejected_when_open_registration_disabled(
    dj_test_client, dj_async_session_maker
) -> None:
    """Forces the late-join + open-registration invariant to apply to dailies."""
    race, token = await _seed_running_daily(dj_async_session_maker)
    async with dj_async_session_maker() as db:
        db_race = await db.get(Race, race.id)
        assert db_race is not None
        db_race.open_registration = False
        await db.commit()
    response = await dj_test_client.post(
        f"/api/races/{race.id}/join",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_daily_join_uses_daily_seed_wording(dj_test_client, dj_async_session_maker) -> None:
    """Joining a daily seed posts 'started the daily seed' (not 'joined the race')."""
    race, token = await _seed_running_daily(dj_async_session_maker)
    response = await dj_test_client.post(
        f"/api/races/{race.id}/join",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200, response.text

    async with dj_async_session_maker() as db:
        result = await db.execute(
            select(ChatMessage).where(
                ChatMessage.race_id == race.id,
                ChatMessage.channel == ChatChannel.PARTICIPANTS,
            )
        )
        messages = [m.message for m in result.scalars().all()]
        assert "Player started the daily seed" in messages
        assert "Player has joined the race" not in messages


@pytest.mark.asyncio
async def test_daily_abandon_uses_daily_seed_wording(
    dj_test_client, dj_async_session_maker
) -> None:
    """Abandoning a daily seed posts 'abandoned the daily seed.' (not the race wording)."""
    race, token = await _seed_running_daily(dj_async_session_maker)
    join_resp = await dj_test_client.post(
        f"/api/races/{race.id}/join",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert join_resp.status_code == 200

    abandon_resp = await dj_test_client.post(
        f"/api/races/{race.id}/abandon",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert abandon_resp.status_code == 200, abandon_resp.text

    async with dj_async_session_maker() as db:
        result = await db.execute(
            select(ChatMessage).where(
                ChatMessage.race_id == race.id,
                ChatMessage.channel == ChatChannel.PUBLIC,
            )
        )
        messages = [m.message for m in result.scalars().all()]
        assert "Player abandoned the daily seed." in messages
        assert "Player has abandoned the race." not in messages


@pytest.mark.asyncio
async def test_daily_finalize_uses_daily_seed_wording(dj_async_session_maker) -> None:
    """finalize_race posts 'The daily seed is over.' on a daily race."""
    from speedfog_racing.services.race_lifecycle import finalize_race

    race, _token = await _seed_running_daily(dj_async_session_maker)

    async with dj_async_session_maker() as db:
        from sqlalchemy.orm import selectinload

        loaded = (
            await db.execute(
                select(Race)
                .where(Race.id == race.id)
                .options(
                    selectinload(Race.participants).selectinload(Participant.user),
                    selectinload(Race.casters),
                    selectinload(Race.seed),
                )
            )
        ).scalar_one()
        loaded.status = RaceStatus.FINISHED
        loaded.finished_at = datetime.now(UTC)
        await db.commit()

        await finalize_race(db, loaded, forced=True)

        result = await db.execute(
            select(ChatMessage).where(
                ChatMessage.race_id == race.id,
                ChatMessage.channel == ChatChannel.PUBLIC,
            )
        )
        messages = [m.message for m in result.scalars().all()]
        assert "The daily seed is over." in messages
        assert "The race has finished." not in messages
