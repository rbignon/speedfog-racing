"""Races in speedrun and Set Seed mode, the speedrun floor on race draws, and
seen seeds: a seed shown before its race started never returns to the draws
that count on the boards."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.config import settings
from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Event,
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedStatus,
    User,
    UserRole,
)
from speedfog_racing.services.speedrun_service import (
    REROLLED_UNRANKED_REASON,
    RESET_UNRANKED_REASON,
    SEEN_SEED_UNRANKED_REASON,
    load_counted_runs,
    load_unranked_runs,
    race_counts_on_boards,
)
from speedfog_racing.services.training_service import (
    SpeedrunStartError,
    create_speedrun_session,
)

from .event_fixtures import bracketed
from .test_admin_events import DOC as EVENT_DOC
from .test_set_seed_service import _seed
from .test_speedrun_service import _add_run, _event, _user
from .test_speedrun_solo import _auth, _available


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


@pytest.fixture
def test_client(async_session):
    async def override_get_db():
        async with async_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    client = AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    yield client
    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _settings(monkeypatch):
    monkeypatch.setattr(settings, "set_seed_min_seed_date", None)
    monkeypatch.setattr(settings, "speedrun_default_floor", 2)


@pytest.fixture
async def pools(async_session):
    async with async_session() as db:
        db.add(Pool(name="sprint", config={"name": "Sprint", "type": "race", "layers_count": 15}))
        db.add(Pool(name="off", enabled=False, config={"name": "Off", "type": "race"}))
        db.add(Pool(name="training_sprint", config={"name": "Sprint", "type": "training"}))
        await db.commit()


@pytest.fixture
def seed_zip(tmp_path) -> str:
    path = tmp_path / "seed.zip"
    path.write_bytes(b"zip")
    return str(path)


async def _staff(db: AsyncSession, name: str, role: UserRole = UserRole.ORGANIZER) -> User:
    user = await _user(db, name)
    user.role = role
    return user


async def _create(client: AsyncClient, body: dict[str, Any]) -> Any:
    return await client.post("/api/races", json={"name": "Ranked", **body}, headers=_auth("org"))


async def _reroll(client: AsyncClient, race_id: str, **body: Any) -> Any:
    return await client.post(
        f"/api/races/{race_id}/reroll-seed", json=body or None, headers=_auth("org")
    )


async def _race_seed(async_session: async_sessionmaker[AsyncSession], race_id: str) -> Seed:
    async with async_session() as db:
        race = await db.get(Race, UUID(race_id))
        assert race is not None and race.seed_id is not None
        seed = await db.get(Seed, race.seed_id)
        assert seed is not None
        return seed


async def _version(async_session: async_sessionmaker[AsyncSession], race_id: str) -> int:
    async with async_session() as db:
        return (await db.execute(select(Race.version).where(Race.id == UUID(race_id)))).scalar_one()


async def _status(async_session: async_sessionmaker[AsyncSession], number: str) -> SeedStatus:
    async with async_session() as db:
        found = (await db.execute(select(Seed).where(Seed.seed_number == number))).scalar_one()
        return found.status


async def _available_count(async_session: async_sessionmaker[AsyncSession], pool: str) -> int:
    async with async_session() as db:
        return (
            await db.execute(
                select(func.count())
                .select_from(Seed)
                .where(Seed.pool_name == pool, Seed.status == SeedStatus.AVAILABLE)
            )
        ).scalar_one()


async def _seed_was_seen(async_session: async_sessionmaker[AsyncSession], race_id: str) -> bool:
    async with async_session() as db:
        return (
            await db.execute(select(Race.seed_was_seen).where(Race.id == UUID(race_id)))
        ).scalar_one()


async def _race_count(async_session: async_sessionmaker[AsyncSession]) -> int:
    async with async_session() as db:
        return (await db.execute(select(func.count()).select_from(Race))).scalar_one()


async def _played(db: AsyncSession, number: str, folder_path: str, *, pool: str = "sprint") -> Seed:
    """A seed with a finished blind race on it: known and replayable."""
    seed = await _seed(db, number, pool=pool, folder_path=folder_path)
    await _add_run(db, user=await _user(db, f"runner-{number}"), igt_ms=1000, minute=1, seed=seed)
    return seed


async def test_create_speedrun_race(test_client, async_session, pools):
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 4)
        await db.commit()

    speedrun = await _create(test_client, {"pool_name": "sprint", "mode": "speedrun"})
    normal = await _create(test_client, {"pool_name": "sprint"})

    assert speedrun.status_code == 201, speedrun.text
    assert speedrun.json()["mode"] == "speedrun"
    assert normal.json()["mode"] == "normal"
    seed = await _race_seed(async_session, speedrun.json()["id"])
    assert (seed.pool_name, seed.status) == ("sprint", SeedStatus.CONSUMED)
    assert await _available_count(async_session, "sprint") == 2


async def test_speedrun_race_refused_at_floor(test_client, async_session, pools):
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 2)  # floor is 2: a draw needs more than 2
        await _available(db, "off", 5)
        await db.commit()

    at_floor = await _create(test_client, {"pool_name": "sprint", "mode": "speedrun"})
    disabled = await _create(test_client, {"pool_name": "off", "mode": "speedrun"})

    assert (at_floor.status_code, at_floor.json()["detail"]) == (409, "No fresh seed right now")
    assert (disabled.status_code, disabled.json()["detail"]) == (
        400,
        "Mode 'off' is not available",
    )
    assert await _race_count(async_session) == 0
    assert await _available_count(async_session, "sprint") == 2
    # The floor guards speedrun draws only.
    assert (await _create(test_client, {"pool_name": "sprint"})).status_code == 201


async def test_speedrun_race_refused_on_training_pool(test_client, async_session, pools):
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "training_sprint", 5)
        await db.commit()

    speedrun = await _create(test_client, {"pool_name": "training_sprint", "mode": "speedrun"})

    assert (speedrun.status_code, speedrun.json()["detail"]) == (
        400,
        "Mode 'training_sprint' is not available",
    )
    assert await _race_count(async_session) == 0
    assert await _available_count(async_session, "training_sprint") == 5
    # A normal race keeps today's checks.
    assert (await _create(test_client, {"pool_name": "training_sprint"})).status_code == 201


async def test_create_set_seed_race(test_client, async_session, pools, seed_zip):
    async with async_session() as db:
        await _staff(db, "org")
        await _played(db, "5eed00000001", seed_zip)
        # A retired (disabled) category's seed stays replayable.
        await _played(db, "0ff000000001", seed_zip, pool="off")
        await _available(db, "sprint", 3)
        await db.commit()
        races_before = await _race_count(async_session)

    race = await _create(
        test_client, {"mode": "set_seed", "seed": "5eed00", "pool_name": "standard"}
    )
    on_retired = await _create(test_client, {"mode": "set_seed", "seed": "0ff000000001"})

    assert race.status_code == 201, race.text
    body = race.json()
    assert (body["mode"], body["pool_name"]) == ("set_seed", "sprint")
    assert (on_retired.status_code, on_retired.json()["pool_name"]) == (201, "off")
    seed = await _race_seed(async_session, body["id"])
    assert (seed.seed_number, seed.status) == ("5eed00000001", SeedStatus.CONSUMED)
    assert await _available_count(async_session, "sprint") == 3
    assert await _race_count(async_session) == races_before + 2


async def test_set_seed_race_refuses_unreplayable_and_unknown(
    test_client, async_session, pools, seed_zip
):
    async with async_session() as db:
        await _staff(db, "org")
        await _played(db, "abcdef111111", seed_zip)
        await _played(db, "abcdef222222", seed_zip)
        blind = await _seed(db, "b11d00000001", folder_path=seed_zip)
        await _add_run(
            db,
            user=await _user(db, "blind"),
            igt_ms=1000,
            minute=2,
            seed=blind,
            race_status=RaceStatus.RUNNING,
        )
        await _seed(db, "fe5400000001", status=SeedStatus.AVAILABLE, folder_path=seed_zip)
        await db.commit()
        races_before = await _race_count(async_session)

    for text, expected in (
        ("zzzzzzzzzzzz", (404, "Unknown seed")),
        ("fe5400000001", (404, "Unknown seed")),  # unplayed: answered like a typo
        ("abcdef", (409, "Ambiguous seed ID")),
        ("b11d00000001", (409, "A blind run on this seed is still in progress.")),
    ):
        response = await _create(test_client, {"mode": "set_seed", "seed": text})
        assert (response.status_code, response.json()["detail"]) == expected, text

    assert await _race_count(async_session) == races_before
    assert await _status(async_session, "fe5400000001") == SeedStatus.AVAILABLE


@pytest.mark.parametrize(
    "body",
    [
        {"mode": "set_seed"},
        {"seed": "abcdef111111"},
        {"mode": "speedrun", "seed": "abcdef111111"},
    ],
)
async def test_seed_required_only_for_set_seed(test_client, async_session, pools, body):
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 4)
        await db.commit()

    assert (await _create(test_client, {"pool_name": "sprint", **body})).status_code == 422


async def test_mode_is_immutable(test_client, async_session, pools):
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 4)
        await db.commit()
    race_id = (await _create(test_client, {"pool_name": "sprint", "mode": "speedrun"})).json()["id"]

    patched = await test_client.patch(
        f"/api/races/{race_id}",
        json={"mode": "normal"},
        headers=_auth("org"),
    )

    assert patched.status_code == 200, patched.text
    fetched = (await test_client.get(f"/api/races/{race_id}")).json()
    assert fetched["mode"] == "speedrun"


async def test_reroll_refused_for_set_seed_race(test_client, async_session, pools, seed_zip):
    async with async_session() as db:
        await _staff(db, "org")
        await _played(db, "5eed00000001", seed_zip)
        await _available(db, "sprint", 3)
        await db.commit()
    race_id = (await _create(test_client, {"mode": "set_seed", "seed": "5eed00000001"})).json()[
        "id"
    ]

    reroll = await _reroll(test_client, race_id)

    assert (reroll.status_code, reroll.json()["detail"]) == (400, "A Set Seed race keeps its seed")
    seed = await _race_seed(async_session, race_id)
    assert (seed.seed_number, seed.status) == ("5eed00000001", SeedStatus.CONSUMED)
    assert await _available_count(async_session, "sprint") == 3


async def test_speedrun_reroll_respects_floor(test_client, async_session, pools):
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 3)
        await db.commit()
    race_id = (await _create(test_client, {"pool_name": "sprint", "mode": "speedrun"})).json()["id"]
    before = await _race_seed(async_session, race_id)
    version = await _version(async_session, race_id)

    reroll = await _reroll(test_client, race_id)

    assert (reroll.status_code, reroll.json()["detail"]) == (409, "No fresh seed right now")
    after = await _race_seed(async_session, race_id)
    assert (after.id, after.status) == (before.id, SeedStatus.CONSUMED)
    assert await _version(async_session, race_id) == version
    assert await _available_count(async_session, "sprint") == 2


async def test_setup_reroll_and_delete_leave_the_seed_seen(test_client, async_session, pools):
    """A SETUP race's seed may have been seen (its map reaches every spectator),
    released or not: a reroll or a deletion makes it SEEN, a report REPORTED.
    A running Daily Seed's seed was played: its reroll keeps it CONSUMED."""
    async with async_session() as db:
        await _staff(db, "org")
        admin = await _staff(db, "admin", UserRole.ADMIN)
        await _available(db, "sprint", 14)
        await db.commit()

    async def current(race_id: str) -> str:
        return (await _race_seed(async_session, race_id)).seed_number

    async def release(race_id: str) -> None:
        response = await test_client.post(
            f"/api/races/{race_id}/release-seeds", headers=_auth("org")
        )
        assert response.status_code == 200, response.text

    async def delete(race_id: str) -> None:
        response = await test_client.delete(f"/api/races/{race_id}", headers=_auth("org"))
        assert response.status_code == 204, response.text

    for mode in ("normal", "speedrun"):
        race_id = (await _create(test_client, {"pool_name": "sprint", "mode": mode})).json()["id"]

        unreleased = await current(race_id)
        assert (await _reroll(test_client, race_id)).status_code == 200
        assert await _status(async_session, unreleased) == SeedStatus.SEEN, mode

        released = await current(race_id)
        await release(race_id)
        assert (await _reroll(test_client, race_id)).status_code == 200
        assert await _status(async_session, released) == SeedStatus.SEEN, mode

        reported = await current(race_id)
        await release(race_id)
        assert (
            await _reroll(test_client, race_id, report_buggy=True, report_reason="Broken gate")
        ).status_code == 200
        assert await _status(async_session, reported) == SeedStatus.REPORTED, mode

        # The reroll cleared the release: an unreleased deletion.
        deleted = await current(race_id)
        await delete(race_id)
        assert await _status(async_session, deleted) == SeedStatus.SEEN, mode

        race_id = (await _create(test_client, {"pool_name": "sprint", "mode": mode})).json()["id"]
        released_deleted = await current(race_id)
        await release(race_id)
        await delete(race_id)
        assert await _status(async_session, released_deleted) == SeedStatus.SEEN, mode

    started = datetime.now(UTC) - timedelta(hours=1)
    async with async_session() as db:
        daily_seed = await _seed(db, "da11y0000001")
        daily = Race(
            name="Daily Seed",
            organizer_id=admin.id,
            seed_id=daily_seed.id,
            status=RaceStatus.RUNNING,
            is_public=True,
            daily_date=started.date(),
            started_at=started,
            seeds_released_at=started,
        )
        db.add(daily)
        await db.commit()
        daily_id = str(daily.id)
    response = await test_client.post(f"/api/races/{daily_id}/reroll-seed", headers=_auth("admin"))
    assert response.status_code == 200, response.text
    assert await current(daily_id) != "da11y0000001"
    assert await _status(async_session, "da11y0000001") == SeedStatus.CONSUMED


@pytest.mark.parametrize("action", ["reroll", "delete"])
@pytest.mark.parametrize("mode", [RunMode.NORMAL])
async def test_reset_race_keeps_its_played_seed_consumed(
    test_client, async_session, pools, mode, action
):
    """A reset brings a race back to SETUP with a seed its runners played: a
    reroll or a deletion keeps that seed CONSUMED. The seed a reroll then draws
    was never played, so the next reroll makes it SEEN."""
    started = datetime.now(UTC) - timedelta(minutes=30)
    async with async_session() as db:
        organizer = await _staff(db, "org")
        await _available(db, "sprint", 5)
        seed = await _seed(db, "5e1f00000001")
        race = Race(
            name="Reset",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            mode=mode,
            started_at=started,
            seeds_released_at=started,
        )
        db.add(race)
        await db.commit()
        race_id = str(race.id)

    reset = await test_client.post(f"/api/races/{race_id}/reset", headers=_auth("org"))
    assert reset.status_code == 200, reset.text
    assert reset.json()["status"] == "setup"
    assert reset.json()["seeds_released_at"] is not None
    if action == "reroll":
        assert (await _reroll(test_client, race_id)).status_code == 200
        drawn = (await _race_seed(async_session, race_id)).seed_number
        assert (await _reroll(test_client, race_id)).status_code == 200
        assert await _status(async_session, drawn) == SeedStatus.SEEN
    else:
        deleted = await test_client.delete(f"/api/races/{race_id}", headers=_auth("org"))
        assert deleted.status_code == 204

    assert await _status(async_session, "5e1f00000001") == SeedStatus.CONSUMED


async def _ranked_race_in(
    async_session: async_sessionmaker[AsyncSession], mode: RunMode, status: RaceStatus
) -> str:
    started = datetime.now(UTC) - timedelta(minutes=30)
    async with async_session() as db:
        organizer = await _staff(db, "org")
        await _available(db, "sprint", 5)
        seed = await _seed(db, "5e1f00000002")
        race = Race(
            name="Reset",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=status,
            mode=mode,
            started_at=started,
            seeds_released_at=started,
        )
        db.add(race)
        await db.commit()
        return str(race.id)


@pytest.mark.parametrize("status", [RaceStatus.RUNNING, RaceStatus.FINISHED])
async def test_speedrun_race_cannot_be_reset(test_client, async_session, pools, status):
    """A reset would replay the seed and count the second attempt as blind."""
    race_id = await _ranked_race_in(async_session, RunMode.SPEEDRUN, status)

    reset = await test_client.post(f"/api/races/{race_id}/reset", headers=_auth("org"))
    assert reset.status_code == 400, reset.text
    assert "speedrun race cannot be reset" in reset.json()["detail"]
    assert "create a new race" in reset.json()["detail"]

    async with async_session() as db:
        race = await db.get(Race, UUID(race_id))
        assert race is not None
        assert race.status == status
        assert race.started_at is not None


@pytest.mark.parametrize("mode", [RunMode.NORMAL, RunMode.SET_SEED])
@pytest.mark.parametrize("status", [RaceStatus.RUNNING, RaceStatus.FINISHED])
async def test_other_races_still_reset(test_client, async_session, pools, mode, status):
    race_id = await _ranked_race_in(async_session, mode, status)

    reset = await test_client.post(f"/api/races/{race_id}/reset", headers=_auth("org"))
    assert reset.status_code == 200, reset.text
    assert reset.json()["status"] == "setup"


async def _unranked_reason(client: AsyncClient, race_id: str) -> str | None:
    response = await client.get(f"/api/races/{race_id}")
    assert response.status_code == 200, response.text
    reason: str | None = response.json()["unranked_reason"]
    return reason


async def _unranked_code(client: AsyncClient, race_id: str) -> str | None:
    response = await client.get(f"/api/races/{race_id}")
    assert response.status_code == 200, response.text
    code: str | None = response.json()["unranked_code"]
    return code


@pytest.mark.parametrize(
    ("kind", "after_reset", "after_reroll"),
    [
        ("community", RESET_UNRANKED_REASON, REROLLED_UNRANKED_REASON),
        ("event", None, None),
    ],
)
async def test_a_reset_community_race_counts_on_no_board_until_a_reported_reroll(
    test_client, async_session, pools, kind, after_reset, after_reroll
):
    """Its runners would replay a seed they played; an event race's reset is
    the admins' call. An unreported reroll gives the race a new seed its
    organizer could fish for (start, reset, reroll), so it stays off."""
    race_id = await _ranked_race_in(async_session, RunMode.NORMAL, RaceStatus.RUNNING)
    if kind == "event":
        async with async_session() as db:
            race = await db.get(Race, UUID(race_id))
            assert race is not None
            race.event_id = (await _event(db)).id
            await db.commit()
    assert await _unranked_reason(test_client, race_id) is None

    reset = await test_client.post(f"/api/races/{race_id}/reset", headers=_auth("org"))
    assert reset.status_code == 200, reset.text
    assert await _unranked_reason(test_client, race_id) == after_reset

    assert (await _reroll(test_client, race_id)).status_code == 200
    assert await _unranked_reason(test_client, race_id) == after_reroll


async def test_a_race_off_for_a_reroll_stays_off_through_a_reset(test_client, async_session, pools):
    """The unreported reroll is for good: once the race is reset, the reason
    it shows is still the reroll, so no seed report is suggested in vain."""
    race_id = await _ranked_race_in(async_session, RunMode.NORMAL, RaceStatus.SETUP)
    assert (await _reroll(test_client, race_id)).status_code == 200
    async with async_session() as db:
        race = await db.get(Race, UUID(race_id))
        assert race is not None
        race.status = RaceStatus.RUNNING
        race.started_at = datetime.now(UTC)
        await db.commit()

    reset = await test_client.post(f"/api/races/{race_id}/reset", headers=_auth("org"))
    assert reset.status_code == 200, reset.text
    assert await _unranked_code(test_client, race_id) == "rerolled"


async def test_a_reported_reroll_puts_a_reset_race_back_on_the_boards(
    test_client, async_session, pools
):
    race_id = await _ranked_race_in(async_session, RunMode.NORMAL, RaceStatus.RUNNING)
    reset = await test_client.post(f"/api/races/{race_id}/reset", headers=_auth("org"))
    assert reset.status_code == 200, reset.text
    assert await _unranked_code(test_client, race_id) == "reset"

    rerolled = await _reroll(test_client, race_id, report_buggy=True, report_reason="Softlock")
    assert rerolled.status_code == 200, rerolled.text
    assert await _unranked_code(test_client, race_id) is None


@pytest.mark.parametrize("mode", ["normal", "speedrun"])
async def test_discarded_seed_stays_discarded(test_client, async_session, pools, mode):
    """A race whose pool was discarded since its creation: rerolling or deleting
    it before the release never revives the seed."""
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 8)
        await db.commit()

    async def discarded_race() -> tuple[str, str]:
        race_id = (await _create(test_client, {"pool_name": "sprint", "mode": mode})).json()["id"]
        seed = await _race_seed(async_session, race_id)
        async with async_session() as db:
            await db.execute(
                update(Seed).where(Seed.id == seed.id).values(status=SeedStatus.DISCARDED)
            )
            await db.commit()
        return race_id, seed.seed_number

    rerolled, rerolled_seed = await discarded_race()
    reported, reported_seed = await discarded_race()
    deleted, deleted_seed = await discarded_race()

    assert (await _reroll(test_client, rerolled)).status_code == 200
    assert (
        await _reroll(test_client, reported, report_buggy=True, report_reason="Broken gate")
    ).status_code == 200
    assert (
        await test_client.delete(f"/api/races/{deleted}", headers=_auth("org"))
    ).status_code == 204
    for number in (rerolled_seed, reported_seed, deleted_seed):
        assert await _status(async_session, number) == SeedStatus.DISCARDED, number


async def test_deleting_set_seed_race_keeps_seed_status(
    test_client, async_session, pools, seed_zip
):
    async with async_session() as db:
        await _staff(db, "org")
        await _played(db, "5eed00000001", seed_zip)
        await db.commit()
    race = await _create(test_client, {"mode": "set_seed", "seed": "5eed00000001"})
    assert race.json()["seeds_released_at"] is None

    deleted = await test_client.delete(f"/api/races/{race.json()['id']}", headers=_auth("org"))

    assert deleted.status_code == 204
    assert await _status(async_session, "5eed00000001") == SeedStatus.CONSUMED


async def test_announcement_carries_the_mode(test_client, async_session, pools, seed_zip):
    async with async_session() as db:
        await _staff(db, "org")
        await _played(db, "5eed00000001", seed_zip)
        await _available(db, "sprint", 4)
        await db.commit()
    public = {
        "is_public": True,
        "scheduled_at": (datetime.now(UTC) + timedelta(hours=2)).isoformat(),
        "open_registration": True,
        "max_participants": 8,
    }

    with (
        patch("speedfog_racing.api.races.notify_race_created", new_callable=AsyncMock) as notify,
        patch("speedfog_racing.api.races.create_calendar_events", new_callable=AsyncMock),
    ):
        for body in (
            {"pool_name": "sprint"},
            {"pool_name": "sprint", "mode": "speedrun"},
            {"mode": "set_seed", "seed": "5eed00"},
        ):
            assert (await _create(test_client, {**public, **body})).status_code == 201
        await asyncio.sleep(0)

    sent = [(call.kwargs["mode"], call.kwargs["seed_number"]) for call in notify.call_args_list]
    # Only a Set Seed race names its seed: a drawn seed stays secret.
    assert sent == [
        (RunMode.NORMAL, None),
        (RunMode.SPEEDRUN, None),
        (RunMode.SET_SEED, "5eed00000001"),
    ]


@pytest.mark.parametrize("status", [RaceStatus.RUNNING, RaceStatus.FINISHED])
async def test_deleting_a_played_race_keeps_its_seed_consumed(
    test_client, async_session, pools, status
):
    race_id = await _ranked_race_in(async_session, RunMode.NORMAL, status)

    deleted = await test_client.delete(f"/api/races/{race_id}", headers=_auth("org"))

    assert deleted.status_code == 204
    assert await _status(async_session, "5e1f00000002") == SeedStatus.CONSUMED


async def _seen(db: AsyncSession, pool: str, count: int) -> list[Seed]:
    return [
        await _seed(db, f"5ee{pool}{i:05d}", pool=pool, status=SeedStatus.SEEN)
        for i in range(count)
    ]


async def test_normal_race_rerolls_never_draw_back_a_seed_they_gave_up(
    test_client, async_session, pools
):
    """At the floor (2 here) a normal race takes SEEN seeds before the
    AVAILABLE reserve, but never one its own rerolls gave up: its rerolls move
    on to the reserve instead of cycling through the seeds it rejected, and
    fail once nothing else is left. Another race may take those seeds."""
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 2)
        seen = {s.seed_number for s in await _seen(db, "sprint", 1)}
        await db.commit()

    race_id = (await _create(test_client, {"pool_name": "sprint"})).json()["id"]
    current = (await _race_seed(async_session, race_id)).seed_number
    assert current in seen
    assert await _seed_was_seen(async_session, race_id)

    gave_up = set()
    for _ in range(2):
        gave_up.add(current)
        assert (await _reroll(test_client, race_id)).status_code == 200
        current = (await _race_seed(async_session, race_id)).seed_number
        assert current not in gave_up
        assert not await _seed_was_seen(async_session, race_id)
        assert await _status(async_session, current) == SeedStatus.CONSUMED
    assert {await _status(async_session, number) for number in gave_up} == {SeedStatus.SEEN}
    assert await _available_count(async_session, "sprint") == 0

    refused = await _reroll(test_client, race_id)
    assert (refused.status_code, refused.json()["detail"]) == (
        400,
        "No other seed left in pool 'sprint' for this race",
    )
    assert (await _race_seed(async_session, race_id)).seed_number == current

    other = (await _create(test_client, {"pool_name": "sprint"})).json()["id"]
    assert (await _race_seed(async_session, other)).seed_number in gave_up
    assert await _seed_was_seen(async_session, other)


@pytest.mark.parametrize(
    ("mode", "kind", "reason"),
    [
        (RunMode.NORMAL, "community", REROLLED_UNRANKED_REASON),
        (RunMode.SPEEDRUN, "community", REROLLED_UNRANKED_REASON),
        (RunMode.NORMAL, "event", None),
    ],
)
async def test_a_reroll_without_a_report_takes_a_community_race_off_the_boards(
    test_client, async_session, pools, mode, kind, reason
):
    """Its organizer may have looked at the seed before giving it up (its
    starting class, or its map in the race's data), so the next one is no
    blind draw; an event race's reroll is the admins' call."""
    race_id = await _ranked_race_in(async_session, mode, RaceStatus.SETUP)
    if kind == "event":
        async with async_session() as db:
            race = await db.get(Race, UUID(race_id))
            assert race is not None
            race.event_id = (await _event(db)).id
            await db.commit()

    assert (await _reroll(test_client, race_id)).status_code == 200
    assert await _unranked_reason(test_client, race_id) == reason
    assert await _unranked_code(test_client, race_id) == ("rerolled" if reason else None)


async def test_a_reported_reroll_keeps_the_race_on_the_boards(test_client, async_session, pools):
    race_id = await _ranked_race_in(async_session, RunMode.NORMAL, RaceStatus.SETUP)

    rerolled = await _reroll(test_client, race_id, report_buggy=True, report_reason="Softlock")
    assert rerolled.status_code == 200, rerolled.text
    assert await _unranked_reason(test_client, race_id) is None

    # A later reroll without a report gives up a seed that could count.
    assert (await _reroll(test_client, race_id)).status_code == 200
    assert await _unranked_reason(test_client, race_id) == REROLLED_UNRANKED_REASON


async def test_a_community_race_on_a_seen_seed_says_it_counts_on_no_board(
    test_client, async_session, pools
):
    """At the floor (2 here) a normal race takes a SEEN seed first; its reroll
    moves on to the AVAILABLE reserve, which puts the race back on the boards."""
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 2)
        await _seen(db, "sprint", 1)
        await db.commit()

    race_id = (await _create(test_client, {"pool_name": "sprint"})).json()["id"]
    assert await _unranked_reason(test_client, race_id) == SEEN_SEED_UNRANKED_REASON

    assert (await _reroll(test_client, race_id)).status_code == 200
    assert await _unranked_reason(test_client, race_id) is None


async def test_ranked_draws_never_take_seen_seeds(test_client, async_session, pools):
    """Speedrun races, Speedrun-mode solo runs, Daily Seeds and event races draw
    AVAILABLE seeds only, and the floor counts AVAILABLE seeds only."""
    async with async_session() as db:
        org = await _staff(db, "org")
        runner = await _user(db, "runner")
        await _available(db, "sprint", 2)  # the floor
        seen = {s.seed_number for s in await _seen(db, "sprint", 5)}
        await db.commit()

    refused = await _create(test_client, {"pool_name": "sprint", "mode": "speedrun"})
    assert (refused.status_code, refused.json()["detail"]) == (409, "No fresh seed right now")
    fresh = await test_client.get("/api/speedrun/fresh-seeds", params={"pool": "sprint"})
    assert fresh.json() == {"fresh": False}
    async with async_session() as db:
        with pytest.raises(SpeedrunStartError) as solo_error:
            await create_speedrun_session(db, runner.id, "sprint")
        assert solo_error.value.code == "no_fresh_seed"

    async with async_session() as db:
        db.add(
            Seed(
                seed_number="f4e5h0000001",
                pool_name="sprint",
                graph_json={"nodes": {}},
                total_layers=15,
                folder_path="/t/fresh",
                status=SeedStatus.AVAILABLE,
            )
        )
        await db.commit()
    speedrun = (await _create(test_client, {"pool_name": "sprint", "mode": "speedrun"})).json()
    assert (await _race_seed(async_session, speedrun["id"])).seed_number not in seen
    reroll = await _reroll(test_client, speedrun["id"])
    assert (reroll.status_code, reroll.json()["detail"]) == (409, "No fresh seed right now")

    # At the floor, a normal race would take a SEEN seed: a Daily Seed's reroll
    # and an event race's reroll take an AVAILABLE one.
    started = datetime.now(UTC) - timedelta(hours=1)
    async with async_session() as db:
        event = await _event(db)
        daily = Race(
            name="Daily Seed",
            organizer_id=org.id,
            seed_id=(await _seed(db, "da11y0000001")).id,
            status=RaceStatus.RUNNING,
            is_public=True,
            daily_date=started.date(),
            started_at=started,
            seeds_released_at=started,
        )
        qualifier = Race(
            name="Qualifier",
            organizer_id=org.id,
            seed_id=(await _seed(db, "e7e470000001")).id,
            status=RaceStatus.SETUP,
            event_id=event.id,
        )
        db.add_all([daily, qualifier])
        await db.commit()
        daily_id, qualifier_id = str(daily.id), str(qualifier.id)
    for race_id in (daily_id, qualifier_id):
        assert (await _reroll(test_client, race_id)).status_code == 200, race_id
        drawn = await _race_seed(async_session, race_id)
        assert drawn.seed_number not in seen, race_id
    assert await _available_count(async_session, "sprint") == 0
    assert await _status(async_session, "da11y0000001") == SeedStatus.CONSUMED
    assert await _status(async_session, "e7e470000001") == SeedStatus.SEEN


async def test_an_event_race_on_a_seen_seed_counts_on_no_board(test_client, async_session, pools):
    """An event race is created as a normal race, which takes a SEEN seed at
    the floor: attached to its event, it counts on no board (its seed page
    lists its runs as Unranked) until a reroll, which for an event race takes
    an AVAILABLE seed and puts it back on the boards."""
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "sprint", 3)  # one above the floor (2)
        await db.commit()

    # No SEEN seed yet: a fresh one.
    fresh = (await _create(test_client, {"pool_name": "sprint"})).json()["id"]
    async with async_session() as db:
        # One more than the races take, for a reroll that would allow SEEN seeds.
        seen = {s.seed_number for s in await _seen(db, "sprint", 3)}
        await db.commit()
    on_seen = (await _create(test_client, {"pool_name": "sprint"})).json()["id"]
    rerolled = (await _create(test_client, {"pool_name": "sprint"})).json()["id"]
    assert (await _race_seed(async_session, fresh)).seed_number not in seen
    for race_id in (on_seen, rerolled):
        assert (await _race_seed(async_session, race_id)).seed_number in seen, race_id

    async with async_session() as db:
        event = await _event(db)
        for race_id in (fresh, on_seen, rerolled):
            race = await db.get(Race, UUID(race_id))
            assert race is not None
            race.event_id = event.id
        await db.commit()

    # At the floor, but an event race's reroll takes the AVAILABLE reserve.
    assert (await _reroll(test_client, rerolled)).status_code == 200
    assert (await _race_seed(async_session, rerolled)).seed_number not in seen
    assert not await _seed_was_seen(async_session, rerolled)

    started = datetime.now(UTC) - timedelta(hours=1)
    async with async_session() as db:
        runner = await _user(db, "runner")
        races = {}
        for race_id in (fresh, on_seen, rerolled):
            race = await db.get(Race, UUID(race_id))
            assert race is not None
            race.status = RaceStatus.FINISHED
            race.started_at = started
            db.add(
                Participant(
                    race_id=race.id,
                    user_id=runner.id,
                    mod_token=f"mt-{race_id}",
                    status=ParticipantStatus.FINISHED,
                    igt_ms=1000,
                    finished_at=started + timedelta(minutes=30),
                )
            )
            races[race_id] = race
        await db.commit()

        counted = {str(run.race_id) for run in await load_counted_runs(db, pool="sprint")}
        assert counted == {fresh, rerolled}
        assert {race_id for race_id, race in races.items() if race_counts_on_boards(race)} == {
            fresh,
            rerolled,
        }
        unranked = await load_unranked_runs(db, races[on_seen].seed_id)
        assert [(str(run.race_id), run.ranked, run.run_type) for run in unranked] == [
            (on_seen, False, "event")
        ]
        for race_id in (fresh, rerolled):
            assert await load_unranked_runs(db, races[race_id].seed_id) == [], race_id


async def test_attaching_a_race_on_a_seen_seed_to_an_event_rerolls_it(
    test_client, async_session, pools
):
    """Attached to an event before its seeds are released, a race that drew a
    SEEN seed is rerolled onto a fresh one, as by its Re-roll button, so its
    runs count on the boards. A race on a fresh seed, one whose seeds are out
    and one whose pool has no fresh seed left keep theirs, and the attach
    itself always goes through."""
    async with async_session() as db:
        await _staff(db, "org")
        await _staff(db, "admin", UserRole.ADMIN)
        await _available(db, "sprint", 3)  # one above the floor (2)
        await db.commit()
    # No SEEN seed yet: a fresh one.
    fresh = (await _create(test_client, {"pool_name": "sprint"})).json()["id"]
    async with async_session() as db:
        seen = {s.seed_number for s in await _seen(db, "sprint", 3)}
        event = Event(
            slug="ev-attach",
            name="Event",
            starts_at=datetime(2026, 9, 23, tzinfo=UTC),
            qualifier_ends_at=datetime(2026, 9, 30, tzinfo=UTC),
            ends_at=datetime(2026, 10, 26, tzinfo=UTC),
            config=bracketed(EVENT_DOC["config"]),
        )
        db.add(event)
        await db.commit()
        event_id = str(event.id)
    unreleased, released, starved = [
        (await _create(test_client, {"pool_name": "sprint"})).json()["id"] for _ in range(3)
    ]
    response = await test_client.post(f"/api/races/{released}/release-seeds", headers=_auth("org"))
    assert response.status_code == 200, response.text
    before = {
        race_id: (await _race_seed(async_session, race_id)).seed_number
        for race_id in (fresh, unreleased, released, starved)
    }
    for race_id in (unreleased, released, starved):
        assert before[race_id] in seen, race_id
    version = await _version(async_session, unreleased)

    async def attach(race_id: str, slot: str) -> Any:
        response = await test_client.post(
            f"/api/admin/races/{race_id}/event",
            json={"event_id": event_id, "slot": slot},
            headers=_auth("admin"),
        )
        assert response.status_code == 200, response.text
        return response.json()

    assert not (await attach(fresh, "semi_a:1"))["seed_was_seen"]
    assert not (await attach(unreleased, "semi_a:2"))["seed_was_seen"]
    assert (await attach(released, "semi_a:3"))["seed_was_seen"]
    async with async_session() as db:
        await db.execute(
            update(Seed)
            .where(Seed.status == SeedStatus.AVAILABLE)
            .values(status=SeedStatus.CONSUMED)
        )
        await db.commit()
    assert (await attach(starved, "final:1"))["seed_was_seen"]

    rerolled = (await _race_seed(async_session, unreleased)).seed_number
    assert rerolled not in seen
    assert not await _seed_was_seen(async_session, unreleased)
    assert await _version(async_session, unreleased) == version + 1
    assert await _status(async_session, before[unreleased]) == SeedStatus.SEEN
    for race_id in (fresh, released, starved):
        assert (await _race_seed(async_session, race_id)).seed_number == before[race_id], race_id
    assert await _seed_was_seen(async_session, starved)


async def test_training_pool_seed_goes_back_available(test_client, async_session, pools):
    """A training pool's seeds are shared practice seeds: a normal race on one
    gives its seed back AVAILABLE on a SETUP reroll or deletion, never SEEN."""
    async with async_session() as db:
        await _staff(db, "org")
        await _available(db, "training_sprint", 4)
        await db.commit()

    race_id = (await _create(test_client, {"pool_name": "training_sprint"})).json()["id"]
    rerolled = (await _race_seed(async_session, race_id)).seed_number
    assert (await _reroll(test_client, race_id)).status_code == 200
    deleted = (await _race_seed(async_session, race_id)).seed_number
    assert (
        await test_client.delete(f"/api/races/{race_id}", headers=_auth("org"))
    ).status_code == 204

    assert await _status(async_session, rerolled) == SeedStatus.AVAILABLE
    assert await _status(async_session, deleted) == SeedStatus.AVAILABLE
    assert await _available_count(async_session, "training_sprint") == 4
