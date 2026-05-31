"""Tests for the Daily Seed lookup API and response shape changes."""

from datetime import UTC, date, datetime, timedelta
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


def test_race_response_populates_my_fields_for_participant() -> None:
    """When the auth'd user is a participant, ``race_response`` mirrors their
    participant row into the ``my_*`` fields so summary surfaces (home,
    dashboard) can render per-user state without needing the full detail."""
    organizer = _user()
    player = _user()
    participant = Participant(
        id=uuid4(),
        user=player,
        user_id=player.id,
        status=ParticipantStatus.PLAYING,
        igt_ms=720_000,
        current_layer=3,
        death_count=2,
    )
    race = _daily_race(organizer=organizer, participants=[participant])
    response = race_response(race, user=player)
    assert response.my_role == "participating"
    assert response.my_participant_status == ParticipantStatus.PLAYING
    assert response.my_current_layer == 3
    assert response.my_igt_ms == 720_000
    assert response.my_death_count == 2


def test_race_response_my_fields_when_organizer_is_also_participant() -> None:
    """``my_role`` keeps its organizer precedence even if the caller also has
    a participant row, but ``my_*`` still mirror that participant row so the
    UI can surface their progress."""
    organizer = _user()
    participant = Participant(
        id=uuid4(),
        user=organizer,
        user_id=organizer.id,
        status=ParticipantStatus.PLAYING,
        igt_ms=480_000,
        current_layer=2,
        death_count=1,
    )
    race = _daily_race(organizer=organizer, participants=[participant])
    response = race_response(race, user=organizer)
    assert response.my_role == "organizing"
    assert response.my_participant_status == ParticipantStatus.PLAYING
    assert response.my_igt_ms == 480_000


def test_race_response_my_fields_none_for_non_participant() -> None:
    organizer = _user()
    bystander = _user()
    race = _daily_race(organizer=organizer)
    response = race_response(race, user=bystander)
    assert response.my_role is None
    assert response.my_participant_status is None
    assert response.my_current_layer is None
    assert response.my_igt_ms is None
    assert response.my_death_count is None


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


def _today_daily() -> date:
    """Match the rotation clock the API uses, so /today resolves to our row."""
    from speedfog_racing.services.daily_seed_loop import daily_date_for

    return daily_date_for(datetime.now(UTC))


@pytest.mark.asyncio
async def test_get_daily_today_returns_current_daily(
    dl_test_client, dl_async_session_maker
) -> None:
    today = _today_daily()
    daily = await _make_daily_db(dl_async_session_maker, day=today)
    response = await dl_test_client.get("/api/daily/today")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(daily.id)
    assert body["daily_date"] == today.isoformat()
    assert body["exclude_from_elo"] is True


@pytest.mark.asyncio
async def test_get_daily_today_returns_404_when_missing(dl_test_client) -> None:
    response = await dl_test_client.get("/api/daily/today")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_daily_by_date_returns_matching_daily(
    dl_test_client, dl_async_session_maker
) -> None:
    target = date(2026, 4, 27)
    daily = await _make_daily_db(dl_async_session_maker, day=target)
    response = await dl_test_client.get(f"/api/daily/{target.isoformat()}")
    assert response.status_code == 200
    body = response.json()
    assert body["id"] == str(daily.id)
    assert body["daily_date"] == target.isoformat()


@pytest.mark.asyncio
async def test_get_daily_by_date_404_for_unknown_date(dl_test_client) -> None:
    response = await dl_test_client.get("/api/daily/2026-04-01")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_get_daily_by_date_404_for_invalid_date(dl_test_client) -> None:
    response = await dl_test_client.get("/api/daily/not-a-date")
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_regular_races_list_excludes_daily_races(
    dl_test_client, dl_async_session_maker
) -> None:
    today = _today_daily()
    daily = await _make_daily_db(dl_async_session_maker, day=today)
    regular = await _make_regular_race(dl_async_session_maker, name="Public Setup")

    response = await dl_test_client.get("/api/races")
    assert response.status_code == 200
    ids = {r["id"] for r in response.json()["races"]}
    assert str(regular.id) in ids
    assert str(daily.id) not in ids


@pytest.mark.asyncio
async def test_joinable_races_list_excludes_daily_races(
    dl_test_client, dl_async_session_maker
) -> None:
    """Even when a daily looks joinable on paper (open registration, running,
    late-join window) it must not appear in /api/races/joinable."""
    today = _today_daily()
    started = datetime(today.year, today.month, today.day, 8, 0, tzinfo=UTC)

    async with dl_async_session_maker() as db:
        sys_user = User(
            twitch_id="sys-joinable",
            twitch_username="sys_join",
            twitch_display_name="System",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        organizer = User(
            twitch_id="org-joinable",
            twitch_username="org_join",
            twitch_display_name="Org",
            api_token=f"tok-org-{uuid4().hex[:6]}",
            role=UserRole.ORGANIZER,
        )
        viewer = User(
            twitch_id="viewer-joinable",
            twitch_username="viewer_join",
            twitch_display_name="Viewer",
            api_token=f"tok-view-{uuid4().hex[:6]}",
            role=UserRole.USER,
        )
        db.add_all([sys_user, organizer, viewer])
        await db.flush()

        daily = Race(
            name=f"Daily Seed - {today.isoformat()}",
            organizer_id=sys_user.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            open_registration=True,
            daily_date=today,
            exclude_from_elo=True,
            started_at=started,
            seeds_released_at=started,
            scheduled_at=started,  # forces /joinable's scheduled_at filter to pass
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
            max_participants=64,
        )
        joinable = Race(
            name="Joinable Race",
            organizer_id=organizer.id,
            status=RaceStatus.SETUP,
            is_public=True,
            open_registration=True,
            scheduled_at=started,
            max_participants=8,
        )
        db.add_all([daily, joinable])
        await db.commit()
        viewer_token = viewer.api_token
        joinable_id = joinable.id
        daily_id = daily.id

    response = await dl_test_client.get(
        "/api/races/joinable", headers={"Authorization": f"Bearer {viewer_token}"}
    )
    assert response.status_code == 200
    ids = {r["id"] for r in response.json()["races"]}
    assert str(joinable_id) in ids
    assert str(daily_id) not in ids


@pytest.mark.asyncio
async def test_recent_daily_returns_past_dailies_only(
    dl_test_client, dl_async_session_maker
) -> None:
    today = _today_daily()
    yesterday = today - timedelta(days=1)
    two_days_ago = today - timedelta(days=2)
    await _make_daily_db(dl_async_session_maker, day=today)
    await _make_daily_db(dl_async_session_maker, day=yesterday, status=RaceStatus.FINISHED)
    await _make_daily_db(dl_async_session_maker, day=two_days_ago, status=RaceStatus.FINISHED)

    response = await dl_test_client.get("/api/daily/recent?limit=2")
    assert response.status_code == 200
    body = response.json()
    daily_dates = [r["daily_date"] for r in body["races"]]
    assert daily_dates == [yesterday.isoformat(), two_days_ago.isoformat()]


@pytest.mark.asyncio
async def test_finished_daily_includes_daily_points_on_participants(
    dl_test_client, dl_async_session_maker
) -> None:
    """A FINISHED daily exposes daily_points per qualified participant."""
    target = date(2026, 5, 10)
    async with dl_async_session_maker() as db:
        organizer = User(
            twitch_id="sys-dp-10",
            twitch_username="sys_dp_10",
            twitch_display_name="System",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        alice = User(
            twitch_id="u-alice-dp",
            twitch_username="alice_dp",
            twitch_display_name="Alice",
            api_token=f"tok-{uuid4().hex[:8]}",
            role=UserRole.USER,
        )
        bob = User(
            twitch_id="u-bob-dp",
            twitch_username="bob_dp",
            twitch_display_name="Bob",
            api_token=f"tok-{uuid4().hex[:8]}",
            role=UserRole.USER,
        )
        carol = User(
            twitch_id="u-carol-dp",
            twitch_username="carol_dp",
            twitch_display_name="Carol",
            api_token=f"tok-{uuid4().hex[:8]}",
            role=UserRole.USER,
        )
        db.add_all([organizer, alice, bob, carol])
        await db.flush()
        started = datetime(2026, 5, 10, 8, 0, tzinfo=UTC)
        race = Race(
            name="Daily Seed - 2026-05-10",
            organizer_id=organizer.id,
            status=RaceStatus.FINISHED,
            is_public=True,
            open_registration=True,
            daily_date=target,
            exclude_from_elo=True,
            started_at=started,
            seeds_released_at=started,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
        )
        db.add(race)
        await db.flush()
        # Three finishers: alice 1st (1000ms), bob 2nd (2000ms), carol 3rd (3000ms).
        # n=3: points are round(100*3/3)=100, round(100*2/3)=67, round(100*1/3)=33.
        for user, igt in [(alice, 1000), (bob, 2000), (carol, 3000)]:
            p = Participant(
                race_id=race.id,
                user_id=user.id,
                status=ParticipantStatus.FINISHED,
                igt_ms=igt,
                current_layer=4,
                death_count=0,
                zone_history=[{"zone": "A"}, {"zone": "B"}],
            )
            db.add(p)
        await db.commit()

    response = await dl_test_client.get(f"/api/daily/{target.isoformat()}")
    assert response.status_code == 200
    by_name = {p["user"]["twitch_username"]: p for p in response.json()["participants"]}
    assert by_name["alice_dp"]["daily_points"] == 100
    assert by_name["bob_dp"]["daily_points"] == 67
    assert by_name["carol_dp"]["daily_points"] == 33


@pytest.mark.asyncio
async def test_running_daily_omits_daily_points(dl_test_client, dl_async_session_maker) -> None:
    """While a daily is RUNNING, daily_points is null on every participant."""
    target = date(2026, 5, 11)
    async with dl_async_session_maker() as db:
        organizer = User(
            twitch_id="sys-dp-11",
            twitch_username="sys_dp_11",
            twitch_display_name="System",
            api_token=None,
            role=UserRole.SYSTEM,
        )
        player = User(
            twitch_id="u-player-dp",
            twitch_username="player_dp",
            twitch_display_name="Player",
            api_token=f"tok-{uuid4().hex[:8]}",
            role=UserRole.USER,
        )
        db.add_all([organizer, player])
        await db.flush()
        started = datetime(2026, 5, 11, 8, 0, tzinfo=UTC)
        race = Race(
            name="Daily Seed - 2026-05-11",
            organizer_id=organizer.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            open_registration=True,
            daily_date=target,
            exclude_from_elo=True,
            started_at=started,
            seeds_released_at=started,
            late_join_window_minutes=1440,
            race_duration_minutes=1440,
        )
        db.add(race)
        await db.flush()
        p = Participant(
            race_id=race.id,
            user_id=player.id,
            status=ParticipantStatus.PLAYING,
            igt_ms=500,
            current_layer=2,
            death_count=0,
            zone_history=[{"zone": "A"}, {"zone": "B"}],
        )
        db.add(p)
        await db.commit()

    response = await dl_test_client.get(f"/api/daily/{target.isoformat()}")
    assert response.status_code == 200
    for p in response.json()["participants"]:
        assert p.get("daily_points") is None
