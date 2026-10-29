"""Races in speedrun and Set Seed mode, the speedrun floor on race draws, and
burned seeds: a seed seen by players never goes back to its pool."""

import asyncio
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, patch
from uuid import UUID

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.config import settings
from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Pool,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedStatus,
    User,
    UserRole,
)

from .test_set_seed_service import _seed
from .test_speedrun_service import _add_run, _user
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
    assert (speedrun.json()["mode"], speedrun.json()["exclude_from_stats"]) == ("speedrun", True)
    assert (normal.json()["mode"], normal.json()["exclude_from_stats"]) == ("normal", False)
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
    assert (body["mode"], body["exclude_from_stats"], body["pool_name"]) == (
        "set_seed",
        True,
        "sprint",
    )
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
        json={"mode": "normal", "exclude_from_stats": False},
        headers=_auth("org"),
    )

    assert patched.status_code == 200, patched.text
    fetched = (await test_client.get(f"/api/races/{race_id}")).json()
    assert (fetched["mode"], fetched["exclude_from_stats"]) == ("speedrun", True)


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


async def test_released_seed_is_burned_on_reroll_and_delete(test_client, async_session, pools):
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
        assert await _status(async_session, unreleased) == SeedStatus.AVAILABLE, mode

        released = await current(race_id)
        await release(race_id)
        assert (await _reroll(test_client, race_id)).status_code == 200
        assert await _status(async_session, released) == SeedStatus.CONSUMED, mode

        reported = await current(race_id)
        await release(race_id)
        assert (
            await _reroll(test_client, race_id, report_buggy=True, report_reason="Broken gate")
        ).status_code == 200
        assert await _status(async_session, reported) == SeedStatus.REPORTED, mode

        # The reroll cleared the release: deleting now gives the seed back.
        returned = await current(race_id)
        await delete(race_id)
        assert await _status(async_session, returned) == SeedStatus.AVAILABLE, mode

        race_id = (await _create(test_client, {"pool_name": "sprint", "mode": mode})).json()["id"]
        burned = await current(race_id)
        await release(race_id)
        await delete(race_id)
        assert await _status(async_session, burned) == SeedStatus.CONSUMED, mode

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
            exclude_from_stats=True,
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
