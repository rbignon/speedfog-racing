"""Tests for late-join and private_dag features."""

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from speedfog_racing.api.helpers import race_response
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
    compute_late_join_deadlines,
)
from speedfog_racing.schemas import CreateRaceRequest
from speedfog_racing.services.hard_close_loop import close_expired_races
from speedfog_racing.services.race_lifecycle import finalize_race


def _base_kwargs(**overrides):
    scheduled_at = datetime.now(UTC) + timedelta(hours=1)
    defaults = dict(name="Test", scheduled_at=scheduled_at)
    defaults.update(overrides)
    return defaults


class TestCreateRaceRequestLateJoin:
    def test_both_null_is_valid(self):
        req = CreateRaceRequest(**_base_kwargs())
        assert req.late_join_window_minutes is None
        assert req.race_duration_minutes is None

    def test_window_requires_duration(self):
        """Setting a late-join window without a race duration is rejected."""
        with pytest.raises(ValidationError, match="race_duration_minutes"):
            CreateRaceRequest(**_base_kwargs(late_join_window_minutes=30))

    def test_window_must_be_le_duration(self):
        with pytest.raises(ValidationError, match="late_join_window_minutes"):
            CreateRaceRequest(
                **_base_kwargs(late_join_window_minutes=120, race_duration_minutes=60)
            )

    def test_duration_must_be_positive(self):
        with pytest.raises(ValidationError, match="race_duration_minutes"):
            CreateRaceRequest(**_base_kwargs(race_duration_minutes=0))

    def test_window_must_be_positive(self):
        with pytest.raises(ValidationError, match="late_join_window_minutes"):
            CreateRaceRequest(**_base_kwargs(late_join_window_minutes=0, race_duration_minutes=120))

    def test_late_join_race_valid(self):
        req = CreateRaceRequest(
            **_base_kwargs(late_join_window_minutes=30, race_duration_minutes=240)
        )
        assert req.late_join_window_minutes == 30
        assert req.race_duration_minutes == 240

    def test_duration_only_without_window_is_valid(self):
        """A hard-close without late-join window is a valid solo-timer race."""
        req = CreateRaceRequest(**_base_kwargs(race_duration_minutes=180))
        assert req.race_duration_minutes == 180
        assert req.late_join_window_minutes is None

    def test_late_join_without_scheduled_at_is_valid(self):
        """Durations no longer depend on scheduled_at (ad-hoc races are fine)."""
        req = CreateRaceRequest(
            name="Ad-hoc",
            scheduled_at=None,
            late_join_window_minutes=30,
            race_duration_minutes=240,
        )
        assert req.late_join_window_minutes == 30


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


def _make_race(
    *,
    status,
    started_at=None,
    late_join_window_minutes=None,
    race_duration_minutes=None,
    private_dag=False,
):
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
        started_at=started_at,
        late_join_window_minutes=late_join_window_minutes,
        race_duration_minutes=race_duration_minutes,
        private_dag=private_dag,
        created_at=datetime.now(UTC),
    )
    race.participants = []
    race.casters = []
    race.seed = None
    return race


def test_compute_late_join_deadlines_resolves_absolutes():
    started = datetime.now(UTC) - timedelta(minutes=5)
    race = _make_race(
        status=RaceStatus.RUNNING,
        started_at=started,
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )
    closes, ends = compute_late_join_deadlines(race)
    assert closes == started + timedelta(minutes=30)
    assert ends == started + timedelta(minutes=240)


def test_compute_late_join_deadlines_none_before_start():
    race = _make_race(
        status=RaceStatus.SETUP,
        started_at=None,
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )
    closes, ends = compute_late_join_deadlines(race)
    assert closes is None
    assert ends is None


def test_race_response_exposes_new_fields():
    started = datetime.now(UTC) - timedelta(minutes=5)
    race = _make_race(
        status=RaceStatus.RUNNING,
        started_at=started,
        late_join_window_minutes=60,
        race_duration_minutes=240,
        private_dag=True,
    )
    resp = race_response(race, user=None)
    assert resp.late_join_window_minutes == 60
    assert resp.race_duration_minutes == 240
    assert resp.registration_closes_at == started + timedelta(minutes=60)
    assert resp.race_ends_at == started + timedelta(minutes=240)
    assert resp.private_dag is True


def test_can_join_true_for_running_race_with_late_join_open():
    race = _make_race(
        status=RaceStatus.RUNNING,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        late_join_window_minutes=60,
        race_duration_minutes=240,
    )
    resp = race_response(race, user=None)
    assert resp.can_join is True


def test_can_join_false_for_running_race_after_deadline():
    race = _make_race(
        status=RaceStatus.RUNNING,
        started_at=datetime.now(UTC) - timedelta(hours=2),
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )
    resp = race_response(race, user=None)
    assert resp.can_join is False


def test_can_join_false_for_running_race_without_late_join():
    race = _make_race(status=RaceStatus.RUNNING, started_at=datetime.now(UTC))
    resp = race_response(race, user=None)
    assert resp.can_join is False


def test_can_join_false_when_registration_not_open_even_with_window():
    """late_join_window_minutes alone must not bypass open_registration=False."""
    race = _make_race(
        status=RaceStatus.RUNNING,
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        late_join_window_minutes=60,
        race_duration_minutes=240,
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
    """A running race past started_at + race_duration_minutes is finalized."""
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
            race_duration_minutes=60,
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
async def test_close_expired_races_stale_version_skipped(hc_async_session):
    """Directly verify the atomic UPDATE's optimistic-lock predicate.

    Regression for the check-then-act race: hard-close filters its UPDATE
    on `version = :v` so a concurrent /finish (which bumps version) causes
    hard-close to see rowcount=0 and skip finalization, preventing duplicate
    "race has finished" messages and double ELO recomputation.
    """
    from sqlalchemy import update as sa_update

    now = datetime.now(UTC)
    async with hc_async_session() as db:
        organizer = await _make_db_user(db, twitch_id="org_stale", role=UserRole.ORGANIZER)
        seed = await _make_db_seed(db, suffix="stale")

        race = Race(
            name="StaleVersion",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now - timedelta(hours=25),
            race_duration_minutes=60,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with hc_async_session() as db:
        race_obj = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        stale_version = race_obj.version

    async with hc_async_session() as other:
        await other.execute(
            sa_update(Race).where(Race.id == race_id).values(version=Race.version + 1)
        )
        await other.commit()

    async with hc_async_session() as db:
        result = await db.execute(
            sa_update(Race)
            .where(
                Race.id == race_id,
                Race.status == RaceStatus.RUNNING,
                Race.version == stale_version,
            )
            .values(
                status=RaceStatus.FINISHED,
                version=stale_version + 1,
                finished_at=datetime.now(UTC),
            )
        )
        await db.commit()
        assert result.rowcount == 0

    async with hc_async_session() as db:
        final = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        assert final.status == RaceStatus.RUNNING


@pytest.mark.asyncio
async def test_close_expired_races_is_idempotent(hc_async_session):
    """Calling close_expired_races twice on the same race only finalizes once."""
    now = datetime.now(UTC)
    async with hc_async_session() as db:
        organizer = await _make_db_user(db, twitch_id="org_idem", role=UserRole.ORGANIZER)
        seed = await _make_db_seed(db, suffix="idem")

        race = Race(
            name="Idempotent",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now - timedelta(hours=25),
            race_duration_minutes=60,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    first = await close_expired_races(hc_async_session)
    second = await close_expired_races(hc_async_session)
    assert race_id in first
    assert race_id not in second


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
            race_duration_minutes=60,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    affected = await close_expired_races(hc_async_session)
    assert race_id not in affected


@pytest.mark.asyncio
async def test_close_expired_races_ignores_race_without_duration(hc_async_session):
    """A running race with no race_duration_minutes must never be force-closed."""
    now = datetime.now(UTC)
    async with hc_async_session() as db:
        organizer = await _make_db_user(db, twitch_id="org_nodur", role=UserRole.ORGANIZER)
        seed = await _make_db_seed(db, suffix="nodur")
        race = Race(
            name="No hard close",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now - timedelta(hours=25),
            race_duration_minutes=None,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    affected = await close_expired_races(hc_async_session)
    assert race_id not in affected


# ---------------------------------------------------------------------------
# HTTP tests for POST /races/{id}/join with late-join
# ---------------------------------------------------------------------------


@pytest.fixture
async def lj_async_engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def lj_async_session(lj_async_engine):
    return async_sessionmaker(lj_async_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture
def lj_test_client(lj_async_session):
    from httpx import ASGITransport, AsyncClient

    from speedfog_racing.database import get_db
    from speedfog_racing.main import app

    async def override_get_db():
        async with lj_async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    transport = ASGITransport(app=app)
    client = AsyncClient(transport=transport, base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture
async def lj_organizer(lj_async_session):
    async with lj_async_session() as db:
        user = User(
            twitch_id="org_lj",
            twitch_username="organizer_lj",
            twitch_display_name="Organizer LJ",
            api_token="org_lj_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


@pytest.fixture
async def lj_player(lj_async_session):
    async with lj_async_session() as db:
        user = User(
            twitch_id="player_lj",
            twitch_username="player_lj",
            twitch_display_name="Player LJ",
            api_token="player_lj_token",
            role=UserRole.USER,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        return user


async def _make_http_seed(db, *, suffix: str) -> Seed:
    seed = Seed(
        seed_number=f"lj_{suffix}",
        pool_name="standard",
        graph_json={"total_layers": 5, "nodes": []},
        total_layers=5,
        folder_path=f"/test/lj_{suffix}",
        status=SeedStatus.CONSUMED,
    )
    db.add(seed)
    await db.flush()
    return seed


async def _create_running_race(
    session_factory,
    *,
    organizer_id,
    suffix: str,
    started_at,
    late_join_window_minutes=None,
    race_duration_minutes=None,
):
    async with session_factory() as db:
        seed = await _make_http_seed(db, suffix=suffix)
        race = Race(
            name=f"Running Race {suffix}",
            organizer_id=organizer_id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            open_registration=True,
            max_participants=10,
            scheduled_at=started_at - timedelta(minutes=20),
            started_at=started_at,
            late_join_window_minutes=late_join_window_minutes,
            race_duration_minutes=race_duration_minutes,
        )
        db.add(race)
        await db.commit()
        await db.refresh(race)
        return race.id


@pytest.mark.asyncio
async def test_join_running_race_with_late_join_open(
    lj_test_client, lj_organizer, lj_player, lj_async_session
):
    """Player can join a RUNNING race while late-join window is open."""
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="open",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        late_join_window_minutes=60,
        race_duration_minutes=240,
    )

    async with lj_test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/join",
            headers={"Authorization": f"Bearer {lj_player.api_token}"},
        )
        assert response.status_code == 200, response.text
        data = response.json()
        assert data["user"]["twitch_username"] == "player_lj"


@pytest.mark.asyncio
async def test_join_running_race_after_deadline(
    lj_test_client, lj_organizer, lj_player, lj_async_session
):
    """Player cannot join a RUNNING race after the late-join deadline passed."""
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="afterd",
        started_at=datetime.now(UTC) - timedelta(hours=2),
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )

    async with lj_test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/join",
            headers={"Authorization": f"Bearer {lj_player.api_token}"},
        )
        assert response.status_code == 400
        assert "closed" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_join_running_race_without_late_join(
    lj_test_client, lj_organizer, lj_player, lj_async_session
):
    """Player cannot join a RUNNING race that has no late-join configured."""
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="nolj",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
    )

    async with lj_test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/join",
            headers={"Authorization": f"Bearer {lj_player.api_token}"},
        )
        assert response.status_code == 400
        assert "setup" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_abandoned_player_cannot_rejoin_late_join_race(
    lj_test_client, lj_organizer, lj_player, lj_async_session
):
    """An ABANDONED participant cannot /join again while late-join is open (409)."""
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="aband",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        late_join_window_minutes=60,
        race_duration_minutes=240,
    )

    async with lj_async_session() as db:
        participant = Participant(
            race_id=race_id,
            user_id=lj_player.id,
            status=ParticipantStatus.ABANDONED,
            color_index=0,
        )
        db.add(participant)
        await db.commit()

    async with lj_test_client as client:
        response = await client.post(
            f"/api/races/{race_id}/join",
            headers={"Authorization": f"Bearer {lj_player.api_token}"},
        )
        assert response.status_code == 409
        assert "already" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_accept_invite_on_late_join_running_race(
    lj_test_client, lj_async_session, lj_organizer, lj_player
):
    """A pending invite can be accepted while late-join is open on a RUNNING race."""
    from speedfog_racing.models import Invite

    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="inv_lj")
        race = Race(
            name="Late-join invite",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            is_public=True,
            open_registration=False,  # invite-only + late-join is a valid combo
            max_participants=10,
            late_join_window_minutes=60,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.flush()
        invite = Invite(race_id=race.id, twitch_username=lj_player.twitch_username)
        db.add(invite)
        await db.commit()
        token = invite.token

    async with lj_test_client as client:
        resp = await client.post(
            f"/api/invite/{token}/accept",
            headers={"Authorization": f"Bearer {lj_player.api_token}"},
        )
    assert resp.status_code == 200, resp.text


@pytest.mark.asyncio
async def test_organizer_can_add_participant_mid_late_join_race(
    lj_test_client, lj_async_session, lj_organizer, lj_player
):
    """Organizer can invite a new participant to a running late-join race."""
    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="org_add_lj")
        race = Race(
            name="Mid-race invite",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=60,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with lj_test_client as client:
        resp = await client.post(
            f"/api/races/{race_id}/participants",
            json={"twitch_username": lj_player.twitch_username},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 200, resp.text


async def test_patch_race_accepts_new_fields_in_setup(
    lj_test_client, lj_async_session, lj_organizer
):
    """SETUP race: PATCH can set durations + private_dag."""
    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_setup")
        race = Race(
            name="Patchable setup",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            scheduled_at=now + timedelta(hours=1),
            is_public=True,
            open_registration=True,
            max_participants=10,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={
                "late_join_window_minutes": 30,
                "race_duration_minutes": 240,
                "private_dag": True,
            },
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["private_dag"] is True
    assert body["late_join_window_minutes"] == 30
    assert body["race_duration_minutes"] == 240


async def test_patch_running_race_can_extend_race_duration(
    lj_test_client, lj_async_session, lj_organizer
):
    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_extend")
        race = Race(
            name="Extend",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=60,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"race_duration_minutes": 300},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 200, resp.text
    assert resp.json()["race_duration_minutes"] == 300


async def test_patch_running_race_cannot_shorten_race_duration(
    lj_test_client, lj_async_session, lj_organizer
):
    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_shorten")
        race = Race(
            name="Shorten",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=60,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"race_duration_minutes": 120},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400
    assert "shorten" in resp.json()["detail"].lower()


async def test_patch_running_race_cannot_change_window(
    lj_test_client, lj_async_session, lj_organizer
):
    """late_join_window_minutes is SETUP-only; editing on RUNNING must 400."""
    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_window_run")
        race = Race(
            name="RunningWindow",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=60,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"late_join_window_minutes": 90},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400
    assert "setup" in resp.json()["detail"].lower()


async def test_patch_running_race_cannot_change_private_dag(
    lj_test_client, lj_async_session, lj_organizer
):
    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_privdag")
        race = Race(
            name="PrivDag",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=60,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"private_dag": True},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400


async def test_joinable_list_includes_running_late_join_race(
    lj_test_client, lj_async_session, lj_organizer, lj_player
):
    """GET /races/joinable must surface RUNNING races whose late-join window is open."""
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="joinable_lj",
        started_at=datetime.now(UTC) - timedelta(minutes=5),
        late_join_window_minutes=60,
        race_duration_minutes=240,
    )

    async with lj_test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {lj_player.api_token}"},
        )
    assert resp.status_code == 200, resp.text
    ids = [r["id"] for r in resp.json()["races"]]
    assert str(race_id) in ids


async def test_joinable_list_excludes_running_race_after_deadline(
    lj_test_client, lj_async_session, lj_organizer, lj_player
):
    """GET /races/joinable must exclude RUNNING races past their late-join deadline."""
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="joinable_past",
        started_at=datetime.now(UTC) - timedelta(hours=2),
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )

    async with lj_test_client as client:
        resp = await client.get(
            "/api/races/joinable",
            headers={"Authorization": f"Bearer {lj_player.api_token}"},
        )
    assert resp.status_code == 200, resp.text
    ids = [r["id"] for r in resp.json()["races"]]
    assert str(race_id) not in ids


async def test_create_race_persists_late_join_and_private_dag(
    lj_test_client, lj_async_session, lj_organizer
):
    """POST /races must persist durations + private_dag."""
    async with lj_async_session() as db:
        seed = Seed(
            seed_number="lj_create_persist",
            pool_name="standard",
            graph_json={"total_layers": 5, "nodes": []},
            total_layers=5,
            folder_path="/test/lj_create_persist",
            status=SeedStatus.AVAILABLE,
        )
        db.add(seed)
        await db.commit()

    scheduled = datetime.now(UTC) + timedelta(hours=1)

    async with lj_test_client as client:
        resp = await client.post(
            "/api/races",
            json={
                "name": "Late-join create",
                "pool_name": "standard",
                "organizer_participates": True,
                "scheduled_at": scheduled.isoformat(),
                "is_public": True,
                "open_registration": True,
                "max_participants": 10,
                "late_join_window_minutes": 30,
                "race_duration_minutes": 240,
                "private_dag": True,
            },
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["late_join_window_minutes"] == 30
    assert body["race_duration_minutes"] == 240
    # Race has not started, so computed absolutes are null.
    assert body["registration_closes_at"] is None
    assert body["race_ends_at"] is None
    assert body["private_dag"] is True


@pytest.mark.asyncio
async def test_get_race_detail_exposes_late_join_and_private_dag(
    lj_test_client, lj_async_session, lj_organizer
):
    """GET /races/:id must return durations + computed absolutes + private_dag."""
    now = datetime.now(UTC)
    started = now - timedelta(minutes=5)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="get_detail_lj")
        race = Race(
            name="Detail late-join",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            scheduled_at=started - timedelta(minutes=20),
            started_at=started,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=60,
            race_duration_minutes=300,
            private_dag=True,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    async with lj_test_client as client:
        resp = await client.get(
            f"/api/races/{race_id}",
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["late_join_window_minutes"] == 60
    assert body["race_duration_minutes"] == 300
    # Computed absolute: started_at + 60 min / 300 min.
    assert body["registration_closes_at"] is not None
    assert body["race_ends_at"] is not None
    assert body["private_dag"] is True


# ---------------------------------------------------------------------------
# PATCH cross-field validation: same invariants as CreateRaceRequest must hold
# after the update.
# ---------------------------------------------------------------------------


async def _make_setup_race(
    session_factory,
    *,
    organizer_id,
    suffix: str,
    scheduled_at,
    late_join_window_minutes=None,
    race_duration_minutes=None,
    private_dag: bool = False,
):
    """Create a SETUP race with the given late-join config and return its id."""
    async with session_factory() as db:
        seed = await _make_http_seed(db, suffix=suffix)
        race = Race(
            name=f"Setup {suffix}",
            organizer_id=organizer_id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            scheduled_at=scheduled_at,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=late_join_window_minutes,
            race_duration_minutes=race_duration_minutes,
            private_dag=private_dag,
        )
        db.add(race)
        await db.commit()
        return race.id


async def test_patch_setup_rejects_window_without_duration(
    lj_test_client, lj_async_session, lj_organizer
):
    """Setting late_join_window_minutes without race_duration_minutes must be rejected."""
    now = datetime.now(UTC)
    race_id = await _make_setup_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="patch_no_duration",
        scheduled_at=now + timedelta(hours=1),
    )

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"late_join_window_minutes": 30},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400, resp.text
    assert "race_duration_minutes" in resp.json()["detail"].lower()


async def test_patch_setup_rejects_window_greater_than_duration(
    lj_test_client, lj_async_session, lj_organizer
):
    """late_join_window_minutes must be <= race_duration_minutes."""
    now = datetime.now(UTC)
    race_id = await _make_setup_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="patch_window_gt_duration",
        scheduled_at=now + timedelta(hours=1),
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"late_join_window_minutes": 300},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400, resp.text
    assert "late_join_window_minutes" in resp.json()["detail"].lower()


async def test_patch_setup_rejects_non_positive_duration(
    lj_test_client, lj_async_session, lj_organizer
):
    now = datetime.now(UTC)
    race_id = await _make_setup_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="patch_zero_duration",
        scheduled_at=now + timedelta(hours=1),
    )

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"race_duration_minutes": 0},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400, resp.text
    assert "race_duration_minutes" in resp.json()["detail"].lower()


# ---------------------------------------------------------------------------
# finalize_race must abandon REGISTERED and READY participants too, not only
# PLAYING. Otherwise late-joiners who never connected leave the race FINISHED
# with stale REGISTERED/READY rows that pollute UI and stats.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_race_abandons_registered_and_ready(hc_async_session):
    """REGISTERED and READY participants must transition to ABANDONED on finalize."""
    from sqlalchemy.orm import selectinload

    now = datetime.now(UTC)
    async with hc_async_session() as db:
        organizer = await _make_db_user(db, twitch_id="org_finalize_rr", role=UserRole.ORGANIZER)
        registered = await _make_db_user(db, twitch_id="late_registered")
        ready = await _make_db_user(db, twitch_id="late_ready")
        playing = await _make_db_user(db, twitch_id="late_playing")
        seed = await _make_db_seed(db, suffix="finalize_rr")

        race = Race(
            name="Finalize REGISTERED+READY",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=now - timedelta(hours=1),
            finished_at=now,
            race_duration_minutes=60,
        )
        db.add(race)
        await db.flush()
        for user, status_, color in (
            (registered, ParticipantStatus.REGISTERED, 0),
            (ready, ParticipantStatus.READY, 1),
            (playing, ParticipantStatus.PLAYING, 2),
        ):
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=user.id,
                    status=status_,
                    color_index=color,
                )
            )
        await db.commit()
        race_id = race.id

    async with hc_async_session() as db:
        race = (
            await db.execute(
                select(Race)
                .where(Race.id == race_id)
                .options(
                    selectinload(Race.participants).selectinload(Participant.user),
                    selectinload(Race.seed),
                )
            )
        ).scalar_one()
        await finalize_race(db, race, forced=True)

    async with hc_async_session() as db:
        statuses = {
            p.user_id: p.status
            for p in (
                await db.execute(select(Participant).where(Participant.race_id == race_id))
            ).scalars()
        }
    assert statuses[registered.id] == ParticipantStatus.ABANDONED
    assert statuses[ready.id] == ParticipantStatus.ABANDONED
    assert statuses[playing.id] == ParticipantStatus.ABANDONED


# ---------------------------------------------------------------------------
# finalize_race must broadcast a leaderboard_update after the auto-abandon
# transitions, otherwise mods keep stale "playing" status for participants
# the hard-close just bumped to ABANDONED and the in-game overlay can't react
# to its own auto-abandon.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_finalize_race_broadcasts_leaderboard_with_abandons(hc_async_session):
    """finalize_race must push the post-abandon participant list to mods."""
    from unittest.mock import AsyncMock
    from unittest.mock import patch as mock_patch

    from sqlalchemy.orm import selectinload

    now = datetime.now(UTC)
    async with hc_async_session() as db:
        organizer = await _make_db_user(db, twitch_id="org_finalize_lb", role=UserRole.ORGANIZER)
        playing = await _make_db_user(db, twitch_id="finalize_lb_playing")
        seed = await _make_db_seed(db, suffix="finalize_lb")
        race = Race(
            name="Finalize broadcasts leaderboard",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.FINISHED,
            started_at=now - timedelta(hours=1),
            finished_at=now,
            race_duration_minutes=60,
        )
        db.add(race)
        await db.flush()
        db.add(
            Participant(
                race_id=race.id,
                user_id=playing.id,
                status=ParticipantStatus.PLAYING,
                color_index=0,
            )
        )
        await db.commit()
        race_id = race.id

    async with hc_async_session() as db:
        race = (
            await db.execute(
                select(Race)
                .where(Race.id == race_id)
                .options(
                    selectinload(Race.participants).selectinload(Participant.user),
                    selectinload(Race.seed),
                )
            )
        ).scalar_one()
        with mock_patch(
            "speedfog_racing.websocket.race.manager.manager.broadcast_leaderboard",
            new=AsyncMock(),
        ) as broadcast_mock:
            await finalize_race(db, race, forced=True)

    broadcast_mock.assert_awaited_once()
    args, _kwargs = broadcast_mock.await_args
    assert args[0] == race_id
    statuses = {p.user_id: p.status for p in args[1]}
    assert statuses[playing.id] == ParticipantStatus.ABANDONED


# ---------------------------------------------------------------------------
# PATCH /races must broadcast a race_info_update so connected mods and
# spectators see field changes without reconnecting.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_patch_running_race_broadcasts_race_info_update(
    lj_test_client, lj_async_session, lj_organizer
):
    """Extending race_duration_minutes on RUNNING must emit race_info_update."""
    from unittest.mock import AsyncMock
    from unittest.mock import patch as mock_patch

    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_bcast")
        race = Race(
            name="Broadcast extend",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=60,
            race_duration_minutes=240,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    with mock_patch(
        "speedfog_racing.api.races.broadcast_race_info_update", new=AsyncMock()
    ) as broadcast_mock:
        async with lj_test_client as client:
            resp = await client.patch(
                f"/api/races/{race_id}",
                json={"race_duration_minutes": 300},
                headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
            )
        assert resp.status_code == 200, resp.text
        broadcast_mock.assert_awaited_once()
        broadcast_race_arg = broadcast_mock.await_args.args[0]
        assert str(broadcast_race_arg.id) == str(race_id)
        assert broadcast_race_arg.race_duration_minutes == 300


@pytest.mark.asyncio
async def test_patch_no_field_change_does_not_broadcast(
    lj_test_client, lj_async_session, lj_organizer
):
    """A no-op PATCH (only fields that didn't actually change) must not broadcast."""
    from unittest.mock import AsyncMock
    from unittest.mock import patch as mock_patch

    now = datetime.now(UTC)
    scheduled = now + timedelta(hours=1)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_noop")
        race = Race(
            name="Noop patch",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            scheduled_at=scheduled,
            is_public=True,
            open_registration=True,
            max_participants=10,
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    with mock_patch(
        "speedfog_racing.api.races.broadcast_race_info_update", new=AsyncMock()
    ) as broadcast_mock:
        async with lj_test_client as client:
            resp = await client.patch(
                f"/api/races/{race_id}",
                json={"is_public": True},  # already True
                headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
            )
        assert resp.status_code == 200, resp.text
        broadcast_mock.assert_not_awaited()


# ---------------------------------------------------------------------------
# POST /races/{id}/start must broadcast race_info_update so mods that authed
# while the race was in SETUP refresh their cached RaceInfo and pick up
# race_ends_at (which only becomes computable once started_at is set).
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_start_race_broadcasts_race_info_update_with_race_ends_at(
    lj_test_client, lj_async_session, lj_organizer, lj_player
):
    """Starting a race with race_duration_minutes must broadcast a fresh RaceInfo."""
    from unittest.mock import AsyncMock
    from unittest.mock import patch as mock_patch

    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="start_bcast")
        race = Race(
            name="Start broadcast",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            seeds_released_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
            late_join_window_minutes=30,
            race_duration_minutes=180,
        )
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=lj_organizer.id, color_index=0))
        db.add(Participant(race_id=race.id, user_id=lj_player.id, color_index=1))
        await db.commit()
        race_id = race.id

    with mock_patch(
        "speedfog_racing.api.races.broadcast_race_info_update", new=AsyncMock()
    ) as broadcast_mock:
        async with lj_test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/start",
                headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
            )
        assert resp.status_code == 200, resp.text
        broadcast_mock.assert_awaited_once()
        broadcast_race_arg = broadcast_mock.await_args.args[0]
        assert str(broadcast_race_arg.id) == str(race_id)
        # The broadcast must carry the just-set started_at so race_ends_at is
        # derivable; otherwise mods that authed in SETUP keep race_ends_at=None.
        assert broadcast_race_arg.started_at is not None
        _, race_ends_at = compute_late_join_deadlines(broadcast_race_arg)
        assert race_ends_at is not None
        started = broadcast_race_arg.started_at
        if started.tzinfo is None:
            started = started.replace(tzinfo=UTC)
        assert race_ends_at - started == timedelta(minutes=180)


@pytest.mark.asyncio
async def test_start_race_broadcasts_race_info_update_without_duration(
    lj_test_client, lj_async_session, lj_organizer, lj_player
):
    """Even without race_duration_minutes, start_race must broadcast a fresh RaceInfo.

    race_ends_at stays None, but spectators and mods still benefit from the
    refreshed started_at so the broadcast must fire unconditionally on
    transition.
    """
    from unittest.mock import AsyncMock
    from unittest.mock import patch as mock_patch

    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="start_bcast_nodur")
        race = Race(
            name="Start broadcast no duration",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            seeds_released_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
        )
        db.add(race)
        await db.flush()
        db.add(Participant(race_id=race.id, user_id=lj_organizer.id, color_index=0))
        db.add(Participant(race_id=race.id, user_id=lj_player.id, color_index=1))
        await db.commit()
        race_id = race.id

    with mock_patch(
        "speedfog_racing.api.races.broadcast_race_info_update", new=AsyncMock()
    ) as broadcast_mock:
        async with lj_test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/start",
                headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
            )
        assert resp.status_code == 200, resp.text
        broadcast_mock.assert_awaited_once()
        broadcast_race_arg = broadcast_mock.await_args.args[0]
        assert broadcast_race_arg.started_at is not None
        _, race_ends_at = compute_late_join_deadlines(broadcast_race_arg)
        assert race_ends_at is None


# ---------------------------------------------------------------------------
# pending_invites must travel in race_state so the organizer's UI sees the
# list update live (in both SETUP and RUNNING/late-join), without reload.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_send_race_state_includes_pending_invites(lj_async_session, lj_organizer):
    """RaceStateMessage must carry pending_invites alongside participants."""
    import json
    from unittest.mock import AsyncMock

    from sqlalchemy.orm import selectinload

    from speedfog_racing.models import Invite
    from speedfog_racing.websocket.race.spectator import send_race_state

    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="pinv_state")
        race = Race(
            name="Pending invites in state",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            scheduled_at=now + timedelta(hours=1),
            is_public=True,
        )
        db.add(race)
        await db.flush()
        for username in ("alice", "bob"):
            db.add(Invite(race_id=race.id, twitch_username=username))
        db.add(Invite(race_id=race.id, twitch_username="charlie", accepted=True))
        await db.commit()
        race_id = race.id

    async with lj_async_session() as db:
        loaded = (
            await db.execute(
                select(Race)
                .where(Race.id == race_id)
                .options(
                    selectinload(Race.organizer),
                    selectinload(Race.seed),
                    selectinload(Race.participants).selectinload(Participant.user),
                )
            )
        ).scalar_one()

        ws = AsyncMock()
        ws.send_text = AsyncMock()

        from speedfog_racing import database as db_module

        original_maker = db_module.async_session_maker
        db_module.async_session_maker = lj_async_session
        try:
            await send_race_state(ws, loaded, locale="en")
        finally:
            db_module.async_session_maker = original_maker

    sent_text = ws.send_text.call_args.args[0]
    payload = json.loads(sent_text)
    pending_usernames = sorted(p["twitch_username"] for p in payload["pending_invites"])
    assert pending_usernames == ["alice", "bob"]
    assert all("token" not in p for p in payload["pending_invites"])


@pytest.mark.asyncio
async def test_revoke_invite_broadcasts_race_state(lj_test_client, lj_async_session, lj_organizer):
    """Revoking a pending invite must emit race_state so the organizer's UI updates."""
    from unittest.mock import AsyncMock
    from unittest.mock import patch as mock_patch

    from speedfog_racing.models import Invite

    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="revoke_bcast")
        race = Race(
            name="Revoke broadcast",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
            open_registration=True,
            max_participants=10,
            scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add(race)
        await db.flush()
        invite = Invite(race_id=race.id, twitch_username="alice")
        db.add(invite)
        await db.commit()
        race_id = race.id
        invite_id = invite.id

    with mock_patch(
        "speedfog_racing.api.races.broadcast_race_state_update", new=AsyncMock()
    ) as bcast:
        async with lj_test_client as client:
            resp = await client.delete(
                f"/api/races/{race_id}/invites/{invite_id}",
                headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
            )
        assert resp.status_code == 204, resp.text
        bcast.assert_awaited_once()


@pytest.mark.asyncio
async def test_add_participant_invite_branch_broadcasts(
    lj_test_client, lj_async_session, lj_organizer
):
    """Creating an invite (organizer adds an unknown twitch_username) must broadcast."""
    from unittest.mock import AsyncMock
    from unittest.mock import patch as mock_patch

    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="addinv_bcast")
        race = Race(
            name="Add invite broadcast",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            is_public=True,
            open_registration=True,
            max_participants=10,
            scheduled_at=datetime.now(UTC) + timedelta(hours=1),
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    with mock_patch(
        "speedfog_racing.api.races.broadcast_race_state_update", new=AsyncMock()
    ) as bcast:
        async with lj_test_client as client:
            resp = await client.post(
                f"/api/races/{race_id}/participants",
                json={"twitch_username": "no_such_user_yet"},
                headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
            )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["invite"] is not None
        assert body["participant"] is None
        bcast.assert_awaited_once()


def test_build_race_info_null_absolutes_before_start():
    """RaceInfo must serialize null ISO strings for the absolutes when not started."""
    from speedfog_racing.websocket.schemas import build_race_info

    race = _make_race(
        status=RaceStatus.SETUP,
        started_at=None,
        late_join_window_minutes=30,
        race_duration_minutes=240,
    )
    info = build_race_info(race)
    assert info.late_join_window_minutes == 30
    assert info.race_duration_minutes == 240
    assert info.registration_closes_at is None
    assert info.race_ends_at is None


def test_race_info_update_message_serialization():
    """RaceInfoUpdateMessage carries the full RaceInfo with type discriminator."""
    import json

    from speedfog_racing.websocket.schemas import RaceInfo, RaceInfoUpdateMessage

    msg = RaceInfoUpdateMessage(
        race=RaceInfo(
            id="abc",
            name="Test",
            status="running",
            late_join_window_minutes=30,
            race_duration_minutes=240,
            race_ends_at="2026-04-21T15:00:00+00:00",
            registration_closes_at="2026-04-21T13:00:00+00:00",
            private_dag=True,
        )
    )
    data = json.loads(msg.model_dump_json())
    assert data["type"] == "race_info_update"
    assert data["race"]["late_join_window_minutes"] == 30
    assert data["race"]["race_duration_minutes"] == 240
    assert data["race"]["race_ends_at"] == "2026-04-21T15:00:00+00:00"
    assert data["race"]["registration_closes_at"] == "2026-04-21T13:00:00+00:00"
    assert data["race"]["private_dag"] is True
