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
async def test_close_expired_races_stale_version_skipped(hc_async_session):
    """Directly verify the atomic UPDATE's optimistic-lock predicate.

    Regression for the check-then-act race: hard-close now filters its UPDATE
    on `version = :v` so a concurrent /finish (which bumps version) causes
    hard-close to see rowcount=0 and skip finalization, preventing duplicate
    "race has finished" messages and double ELO recomputation.

    We exercise the exact predicate the fix added: load the race, let another
    session bump the version, then issue the guarded UPDATE with the stale
    version and assert rowcount is 0.
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
            race_ends_at=now - timedelta(minutes=5),
        )
        db.add(race)
        await db.commit()
        race_id = race.id

    # Load the race as the hard-close loop does
    async with hc_async_session() as db:
        race_obj = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        stale_version = race_obj.version

    # Concurrent /finish bumps the version
    async with hc_async_session() as other:
        await other.execute(
            sa_update(Race).where(Race.id == race_id).values(version=Race.version + 1)
        )
        await other.commit()

    # The guarded UPDATE the hard-close loop issues must now fail the predicate
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

    # And the race must still be RUNNING (hard-close did not finalize)
    async with hc_async_session() as db:
        final = (await db.execute(select(Race).where(Race.id == race_id))).scalar_one()
        assert final.status == RaceStatus.RUNNING


@pytest.mark.asyncio
async def test_close_expired_races_is_idempotent(hc_async_session):
    """Calling close_expired_races twice on the same race only finalizes once.

    Second call must be a no-op because the race is already FINISHED.
    """
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
            race_ends_at=now - timedelta(minutes=5),
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
            race_ends_at=now + timedelta(hours=1),
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
    registration_closes_at,
    race_ends_at=None,
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
            scheduled_at=datetime.now(UTC) - timedelta(minutes=30),
            started_at=datetime.now(UTC) - timedelta(minutes=10),
            registration_closes_at=registration_closes_at,
            race_ends_at=race_ends_at,
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
    now = datetime.now(UTC)
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="open",
        registration_closes_at=now + timedelta(hours=1),
        race_ends_at=now + timedelta(hours=4),
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
    now = datetime.now(UTC)
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="afterd",
        registration_closes_at=now - timedelta(minutes=1),
        race_ends_at=now + timedelta(hours=4),
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
        registration_closes_at=None,
        race_ends_at=None,
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
    now = datetime.now(UTC)
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="aband",
        registration_closes_at=now + timedelta(hours=1),
        race_ends_at=now + timedelta(hours=4),
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
            registration_closes_at=now + timedelta(hours=1),
            race_ends_at=now + timedelta(hours=4),
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
            registration_closes_at=now + timedelta(hours=1),
            race_ends_at=now + timedelta(hours=4),
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
    """SETUP race: PATCH can set all three new fields."""
    now = datetime.now(UTC)
    scheduled = now + timedelta(hours=1)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_setup")
        race = Race(
            name="Patchable setup",
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

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={
                "registration_closes_at": (scheduled + timedelta(minutes=30)).isoformat(),
                "race_ends_at": (scheduled + timedelta(hours=4)).isoformat(),
                "private_dag": True,
            },
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["private_dag"] is True
    assert body["registration_closes_at"] is not None
    assert body["race_ends_at"] is not None


async def test_patch_running_race_can_extend_race_ends_at(
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
            registration_closes_at=now + timedelta(hours=1),
            race_ends_at=now + timedelta(hours=4),
        )
        db.add(race)
        await db.commit()
        race_id = race.id
        current_end = race.race_ends_at

    new_end = current_end + timedelta(hours=1)
    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"race_ends_at": new_end.isoformat()},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 200, resp.text


async def test_patch_running_race_cannot_shorten_race_ends_at(
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
            registration_closes_at=now + timedelta(hours=1),
            race_ends_at=now + timedelta(hours=4),
        )
        db.add(race)
        await db.commit()
        race_id = race.id
        current_end = race.race_ends_at

    shorter = current_end - timedelta(minutes=10)
    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"race_ends_at": shorter.isoformat()},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400
    assert "shorten" in resp.json()["detail"].lower()


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
            registration_closes_at=now + timedelta(hours=1),
            race_ends_at=now + timedelta(hours=4),
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
    now = datetime.now(UTC)
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="joinable_lj",
        registration_closes_at=now + timedelta(hours=1),
        race_ends_at=now + timedelta(hours=4),
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
    now = datetime.now(UTC)
    race_id = await _create_running_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="joinable_past",
        registration_closes_at=now - timedelta(minutes=1),
        race_ends_at=now + timedelta(hours=4),
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
    """POST /races must persist registration_closes_at, race_ends_at, private_dag."""
    # Seed an AVAILABLE seed so create_race's assign_seed_to_race succeeds.
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
    reg_closes = scheduled + timedelta(minutes=30)
    race_ends = scheduled + timedelta(hours=4)

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
                "registration_closes_at": reg_closes.isoformat(),
                "race_ends_at": race_ends.isoformat(),
                "private_dag": True,
            },
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )

    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["registration_closes_at"] is not None
    assert body["race_ends_at"] is not None
    assert body["private_dag"] is True


@pytest.mark.asyncio
async def test_get_race_detail_exposes_late_join_and_private_dag(
    lj_test_client, lj_async_session, lj_organizer
):
    """GET /races/:id must return registration_closes_at, race_ends_at, private_dag."""
    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="get_detail_lj")
        race = Race(
            name="Detail late-join",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.SETUP,
            scheduled_at=now + timedelta(hours=1),
            is_public=True,
            open_registration=True,
            max_participants=10,
            registration_closes_at=now + timedelta(hours=2),
            race_ends_at=now + timedelta(hours=5),
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
    assert body["registration_closes_at"] is not None
    assert body["race_ends_at"] is not None
    assert body["private_dag"] is True


# ---------------------------------------------------------------------------
# PATCH cross-field validation: same invariants as CreateRaceRequest must hold
# after the update. These guard against the gross errors fixed in e0fb234 /
# 1af1da6 by ensuring the PATCH path doesn't drop fields silently or leave
# the race in an internally-inconsistent state.
# ---------------------------------------------------------------------------


async def _make_setup_race(
    session_factory,
    *,
    organizer_id,
    suffix: str,
    scheduled_at,
    registration_closes_at=None,
    race_ends_at=None,
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
            registration_closes_at=registration_closes_at,
            race_ends_at=race_ends_at,
            private_dag=private_dag,
        )
        db.add(race)
        await db.commit()
        return race.id


async def test_patch_setup_rejects_clearing_scheduled_at_with_late_join(
    lj_test_client, lj_async_session, lj_organizer
):
    """Clearing scheduled_at while registration_closes_at is set must be rejected."""
    now = datetime.now(UTC)
    scheduled = now + timedelta(hours=1)
    race_id = await _make_setup_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="patch_clear_sched",
        scheduled_at=scheduled,
        registration_closes_at=scheduled + timedelta(minutes=30),
        race_ends_at=scheduled + timedelta(hours=4),
    )

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"scheduled_at": None},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400, resp.text
    assert "scheduled_at" in resp.json()["detail"].lower()


async def test_patch_setup_rejects_late_registration_without_race_ends_at(
    lj_test_client, lj_async_session, lj_organizer
):
    """If registration_closes_at > scheduled_at then race_ends_at is required."""
    now = datetime.now(UTC)
    scheduled = now + timedelta(hours=1)
    race_id = await _make_setup_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="patch_late_no_end",
        scheduled_at=scheduled,
    )

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"registration_closes_at": (scheduled + timedelta(minutes=30)).isoformat()},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400, resp.text
    assert "race_ends_at" in resp.json()["detail"].lower()


async def test_patch_setup_rejects_registration_after_race_ends_at(
    lj_test_client, lj_async_session, lj_organizer
):
    """registration_closes_at must be <= race_ends_at."""
    now = datetime.now(UTC)
    scheduled = now + timedelta(hours=1)
    race_id = await _make_setup_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="patch_reg_gt_end",
        scheduled_at=scheduled,
        registration_closes_at=scheduled + timedelta(minutes=30),
        race_ends_at=scheduled + timedelta(hours=4),
    )

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"registration_closes_at": (scheduled + timedelta(hours=5)).isoformat()},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400, resp.text
    assert "registration_closes_at" in resp.json()["detail"].lower()


async def test_patch_setup_rejects_race_ends_at_before_scheduled_at(
    lj_test_client, lj_async_session, lj_organizer
):
    """race_ends_at must be after scheduled_at."""
    now = datetime.now(UTC)
    scheduled = now + timedelta(hours=2)
    race_id = await _make_setup_race(
        lj_async_session,
        organizer_id=lj_organizer.id,
        suffix="patch_end_lt_sched",
        scheduled_at=scheduled,
    )

    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"race_ends_at": (scheduled - timedelta(minutes=10)).isoformat()},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code == 400, resp.text
    assert "race_ends_at" in resp.json()["detail"].lower()


async def test_patch_running_extend_accepts_naive_iso(
    lj_test_client, lj_async_session, lj_organizer
):
    """A naive ISO datetime (no offset) must not crash the comparison."""
    now = datetime.now(UTC)
    async with lj_async_session() as db:
        seed = await _make_http_seed(db, suffix="patch_naive")
        race = Race(
            name="Naive Extend",
            organizer_id=lj_organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            started_at=now,
            is_public=True,
            open_registration=True,
            max_participants=10,
            registration_closes_at=now + timedelta(hours=1),
            race_ends_at=now + timedelta(hours=4),
        )
        db.add(race)
        await db.commit()
        race_id = race.id
        current_end = race.race_ends_at

    new_end_naive = (current_end + timedelta(hours=1)).replace(tzinfo=None).isoformat()
    async with lj_test_client as client:
        resp = await client.patch(
            f"/api/races/{race_id}",
            json={"race_ends_at": new_end_naive},
            headers={"Authorization": f"Bearer {lj_organizer.api_token}"},
        )
    assert resp.status_code in (200, 400), resp.text
    # Critical assertion: the comparison did not raise a 500 due to naive/aware mismatch.
    assert resp.status_code != 500


# PLACEHOLDER_FINALIZE_TESTS
