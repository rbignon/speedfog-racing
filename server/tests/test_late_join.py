"""Tests for late-join and private_dag features."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError

from speedfog_racing.api.helpers import race_response
from speedfog_racing.models import Race, RaceStatus, User
from speedfog_racing.schemas import CreateRaceRequest
from speedfog_racing.services.race_lifecycle import finalize_race


def _base_kwargs(**overrides):
    scheduled_at = datetime.now(UTC) + timedelta(hours=1)
    defaults = dict(name="Test", scheduled_at=scheduled_at)
    defaults.update(overrides)
    return defaults


class TestCreateRaceRequestLateJoin:
    def test_both_null_is_valid(self):
        req = CreateRaceRequest(**_base_kwargs())
        assert req.registration_closes_at is None
        assert req.race_ends_at is None

    def test_registration_after_scheduled_requires_race_ends_at(self):
        scheduled = datetime.now(UTC) + timedelta(hours=1)
        with pytest.raises(ValidationError, match="race_ends_at"):
            CreateRaceRequest(
                **_base_kwargs(
                    scheduled_at=scheduled,
                    registration_closes_at=scheduled + timedelta(minutes=30),
                )
            )

    def test_registration_closes_at_must_be_before_race_ends_at(self):
        scheduled = datetime.now(UTC) + timedelta(hours=1)
        with pytest.raises(ValidationError, match="registration_closes_at"):
            CreateRaceRequest(
                **_base_kwargs(
                    scheduled_at=scheduled,
                    registration_closes_at=scheduled + timedelta(hours=5),
                    race_ends_at=scheduled + timedelta(hours=2),
                )
            )

    def test_race_ends_at_must_be_after_scheduled(self):
        scheduled = datetime.now(UTC) + timedelta(hours=1)
        with pytest.raises(ValidationError, match="race_ends_at"):
            CreateRaceRequest(
                **_base_kwargs(
                    scheduled_at=scheduled,
                    race_ends_at=scheduled - timedelta(minutes=1),
                )
            )

    def test_late_join_race_valid(self):
        scheduled = datetime.now(UTC) + timedelta(hours=1)
        req = CreateRaceRequest(
            **_base_kwargs(
                scheduled_at=scheduled,
                registration_closes_at=scheduled + timedelta(minutes=30),
                race_ends_at=scheduled + timedelta(hours=4),
            )
        )
        assert req.registration_closes_at == scheduled + timedelta(minutes=30)
        assert req.race_ends_at == scheduled + timedelta(hours=4)

    def test_registration_without_scheduled_rejected(self):
        with pytest.raises(ValidationError, match="scheduled_at"):
            CreateRaceRequest(
                name="Test",
                scheduled_at=None,
                registration_closes_at=datetime.now(UTC) + timedelta(hours=1),
                race_ends_at=datetime.now(UTC) + timedelta(hours=4),
            )


def _make_user(**kw) -> User:
    defaults = dict(
        id=uuid4(),
        twitch_id=f"user-{uuid4()}",
        twitch_username=f"user-{uuid4().hex[:6]}",
        twitch_display_name="Test User",
        twitch_avatar_url=None,
    )
    defaults.update(kw)
    return User(**defaults)


def _make_race(*, status, registration_closes_at=None, race_ends_at=None, private_dag=False):
    organizer = _make_user()
    race = Race(
        id=uuid4(),
        name="R",
        organizer_id=organizer.id,
        organizer=organizer,
        status=status,
        is_public=True,
        open_registration=True,
        max_participants=10,
        registration_closes_at=registration_closes_at,
        race_ends_at=race_ends_at,
        private_dag=private_dag,
        created_at=datetime.now(UTC),
    )
    race.participants = []
    race.casters = []
    race.seed = None
    return race


def test_race_response_exposes_new_fields():
    now = datetime.now(UTC)
    race = _make_race(
        status=RaceStatus.RUNNING,
        registration_closes_at=now + timedelta(hours=1),
        race_ends_at=now + timedelta(hours=4),
        private_dag=True,
    )
    resp = race_response(race, user=None)
    assert resp.registration_closes_at == race.registration_closes_at
    assert resp.race_ends_at == race.race_ends_at
    assert resp.private_dag is True


def test_can_join_true_for_running_race_with_late_join_open():
    now = datetime.now(UTC)
    race = _make_race(
        status=RaceStatus.RUNNING,
        registration_closes_at=now + timedelta(hours=1),
        race_ends_at=now + timedelta(hours=4),
    )
    resp = race_response(race, user=None)
    assert resp.can_join is True


def test_can_join_false_for_running_race_after_deadline():
    now = datetime.now(UTC)
    race = _make_race(
        status=RaceStatus.RUNNING,
        registration_closes_at=now - timedelta(minutes=1),
        race_ends_at=now + timedelta(hours=4),
    )
    resp = race_response(race, user=None)
    assert resp.can_join is False


def test_can_join_false_for_running_race_without_late_join():
    race = _make_race(status=RaceStatus.RUNNING)
    resp = race_response(race, user=None)
    assert resp.can_join is False


def test_can_join_false_when_registration_not_open_even_with_deadline():
    """registration_closes_at alone must not bypass open_registration=False."""
    now = datetime.now(UTC)
    race = _make_race(
        status=RaceStatus.RUNNING,
        registration_closes_at=now + timedelta(hours=1),
        race_ends_at=now + timedelta(hours=4),
    )
    race.open_registration = False
    resp = race_response(race, user=None)
    assert resp.can_join is False


def test_finalize_race_helper_is_importable():
    import inspect

    sig = inspect.signature(finalize_race)
    assert set(sig.parameters.keys()) == {"db", "race", "forced"}


# ---------------------------------------------------------------------------
# hard_close_loop tests
# ---------------------------------------------------------------------------

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from speedfog_racing.database import Base  # noqa: E402
from speedfog_racing.models import (  # noqa: E402
    Participant,
    ParticipantStatus,
    Seed,
    SeedStatus,
    UserRole,
)
from speedfog_racing.services.hard_close_loop import close_expired_races  # noqa: E402


@pytest.fixture
async def hc_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
def hc_async_session(hc_async_engine):
    return async_sessionmaker(hc_async_engine, class_=AsyncSession, expire_on_commit=False)


async def _make_db_user(db, *, twitch_id: str, role: UserRole = UserRole.USER) -> User:
    user = User(
        twitch_id=twitch_id,
        twitch_username=twitch_id,
        twitch_display_name=twitch_id,
        api_token=f"{twitch_id}_tok",
        role=role,
    )
    db.add(user)
    await db.flush()
    return user


async def _make_db_seed(db, *, suffix: str) -> Seed:
    seed = Seed(
        seed_number=f"s_{suffix}",
        pool_name="standard",
        graph_json={"total_layers": 5, "nodes": []},
        total_layers=5,
        folder_path=f"/test/{suffix}",
        status=SeedStatus.CONSUMED,
    )
    db.add(seed)
    await db.flush()
    return seed


@pytest.mark.asyncio
async def test_close_expired_races_transitions_to_finished(hc_async_session):
    """A running race past its race_ends_at is finalized, PLAYING participants go to ABANDONED."""
    now = datetime.now(UTC)
    async with hc_async_session() as db:
        organizer = await _make_db_user(db, twitch_id="org_hc1", role=UserRole.ORGANIZER)
        player = await _make_db_user(db, twitch_id="player_hc1")
        seed = await _make_db_seed(db, suffix="hc1")

        race = Race(
            name="Expired",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now - timedelta(hours=25),
            race_ends_at=now - timedelta(minutes=5),
        )
        db.add(race)
        await db.flush()
        participant = Participant(
            race_id=race.id,
            user_id=player.id,
            status=ParticipantStatus.PLAYING,
            color_index=0,
        )
        db.add(participant)
        await db.commit()
        race_id = race.id

    affected = await close_expired_races(hc_async_session)
    assert race_id in affected

    async with hc_async_session() as db:
        race = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        assert race.status == RaceStatus.FINISHED
        part = (
            await db.execute(select(Participant).where(Participant.race_id == race_id))
        ).scalar_one()
        assert part.status == ParticipantStatus.ABANDONED


@pytest.mark.asyncio
async def test_close_expired_races_skips_non_expired(hc_async_session):
    now = datetime.now(UTC)
    async with hc_async_session() as db:
        organizer = await _make_db_user(db, twitch_id="org_hc2", role=UserRole.ORGANIZER)
        seed = await _make_db_seed(db, suffix="hc2")

        race = Race(
            name="Fresh",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            race_ends_at=now + timedelta(hours=1),
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    affected = await close_expired_races(hc_async_session)
    assert race_id not in affected
