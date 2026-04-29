"""Tests for the Daily Seed lookup API and response shape changes."""

from datetime import UTC, date, datetime
from uuid import uuid4

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.api.helpers import race_response
from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceStatus,
    User,
    UserRole,
)


def _user(**overrides) -> User:
    defaults = dict(
        id=uuid4(),
        twitch_id=f"u-{uuid4().hex[:8]}",
        twitch_username=f"user-{uuid4().hex[:6]}",
        twitch_display_name="User",
        twitch_avatar_url=None,
        api_token=f"tok-{uuid4().hex[:8]}",
        role=UserRole.USER,
    )
    defaults.update(overrides)
    return User(**defaults)


def _daily_race(*, organizer: User, **overrides) -> Race:
    started = datetime(2026, 4, 27, 8, 0, tzinfo=UTC)
    defaults = dict(
        id=uuid4(),
        name="Daily Seed - 2026-04-27",
        organizer_id=organizer.id,
        organizer=organizer,
        status=RaceStatus.RUNNING,
        is_public=True,
        open_registration=True,
        private_dag=False,
        daily_date=date(2026, 4, 27),
        exclude_from_elo=True,
        started_at=started,
        seeds_released_at=started,
        late_join_window_minutes=1440,
        race_duration_minutes=1440,
        created_at=datetime(2026, 4, 27, 7, 30, tzinfo=UTC),
        participants=[],
        casters=[],
    )
    defaults.update(overrides)
    return Race(**defaults)


def test_race_response_includes_daily_fields() -> None:
    organizer = _user()
    race = _daily_race(organizer=organizer)
    response = race_response(race, user=None)
    assert response.daily_date == date(2026, 4, 27)
    assert response.exclude_from_elo is True


def test_participant_preview_includes_status_and_igt() -> None:
    organizer = _user()
    player = _user()
    participant = Participant(
        id=uuid4(),
        user=player,
        user_id=player.id,
        status=ParticipantStatus.FINISHED,
        igt_ms=2_520_000,
        current_layer=4,
        death_count=1,
    )
    race = _daily_race(
        organizer=organizer,
        status=RaceStatus.FINISHED,
        finished_at=datetime(2026, 4, 27, 10, 0, tzinfo=UTC),
        participants=[participant],
    )
    response = race_response(race, user=player)
    assert response.participant_previews
    preview = response.participant_previews[0]
    assert preview.status == ParticipantStatus.FINISHED
    assert preview.igt_ms == 2_520_000
    assert preview.placement == 1


def test_participant_preview_omits_igt_when_not_finished() -> None:
    organizer = _user()
    player = _user()
    participant = Participant(
        id=uuid4(),
        user=player,
        user_id=player.id,
        status=ParticipantStatus.REGISTERED,
        igt_ms=0,
        current_layer=0,
        death_count=0,
    )
    race = _daily_race(organizer=organizer, participants=[participant])
    preview = race_response(race, user=player).participant_previews[0]
    assert preview.status == ParticipantStatus.REGISTERED
    assert preview.igt_ms is None


# ---------------------------------------------------------------------------
# HTTP fixtures and tests for /api/daily/* endpoints (filled in Task 2)
# ---------------------------------------------------------------------------


@pytest.fixture
async def dl_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def dl_async_session_maker(dl_async_engine):
    return async_sessionmaker(dl_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def dl_test_client(dl_async_session_maker):
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.database import get_db
    from speedfog_racing.main import app

    async def override_get_db():
        async with dl_async_session_maker() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


async def _make_daily_db(
    session_maker, *, day: date, status: RaceStatus = RaceStatus.RUNNING
) -> Race:
    """Insert a daily race into the test DB and return the persisted row."""
    async with session_maker() as db:
        organizer = User(
            twitch_id=f"sys-{day.isoformat()}",
            twitch_username=f"sys_{day.isoformat()}",
            twitch_display_name="System",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        db.add(organizer)
        await db.flush()
        started = datetime.combine(day, datetime.min.time(), tzinfo=UTC).replace(hour=8)
        race = Race(
            name=f"Daily Seed - {day.isoformat()}",
            organizer_id=organizer.id,
            status=status,
            is_public=True,
            open_registration=True,
            daily_date=day,
            exclude_from_elo=True,
            started_at=started,
            seeds_released_at=started,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return race


async def _make_regular_race(session_maker, *, name: str = "Regular Race") -> Race:
    async with session_maker() as db:
        organizer = User(
            twitch_id=f"org-{uuid4().hex[:6]}",
            twitch_username=f"org_{uuid4().hex[:6]}",
            twitch_display_name="Org",
            api_token=f"tok-{uuid4().hex[:8]}",
            role=UserRole.ORGANIZER,
        )
        db.add(organizer)
        await db.flush()
        race = Race(
            name=name,
            organizer_id=organizer.id,
            status=RaceStatus.SETUP,
            is_public=True,
            open_registration=True,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return race
