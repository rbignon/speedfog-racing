"""GET /api/speedrun/seeds/{seed}, seed protections, admin Set Seed exclusions,
and the run mode on race and session responses."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.config import settings
from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Pool,
    Race,
    RaceStatus,
    RunMode,
    Seed,
    SeedProtection,
    SeedStatus,
    TrainingSessionStatus,
    UserRole,
)

from .test_set_seed_service import _seed
from .test_speedrun_service import BASE, _add_run, _add_session, _user


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


@pytest.fixture
async def pools(async_session):
    async with async_session() as db:
        # conftest creates "standard" with every pools table; give it a layer count.
        standard = (await db.execute(select(Pool).where(Pool.name == "standard"))).scalar_one()
        standard.config = {"name": "Standard", "type": "race", "layers_count": 30}
        db.add(Pool(name="sprint", config={"name": "Sprint", "type": "race", "layers_count": 15}))
        await db.commit()


@pytest.fixture(autouse=True)
def _set_seed_settings(monkeypatch):
    """The documented defaults, whatever the local .env says."""
    monkeypatch.setattr(settings, "set_seed_min_seed_date", None)
    monkeypatch.setattr(settings, "set_seed_kept_top_seeds", 10)
    monkeypatch.setattr(settings, "seed_protection_limit", 3)
    monkeypatch.setattr(settings, "seed_purge_grace_days", 30)


def _auth(name: str) -> dict[str, str]:
    return {"Authorization": f"Bearer tok-{name}"}


async def _page(client: AsyncClient, number: str, viewer: str | None = None) -> dict[str, Any]:
    response = await client.get(
        f"/api/speedrun/seeds/{number}", headers=_auth(viewer) if viewer else None
    )
    assert response.status_code == 200, response.text
    data: dict[str, Any] = response.json()
    return data


async def _played_at(db: AsyncSession, participant: Participant, when: datetime) -> None:
    """Move a run's race (start, finish, creation) and finish to ``when``."""
    race = await db.get(Race, participant.race_id)
    assert race is not None
    race.created_at = race.started_at = race.finished_at = when
    participant.finished_at = when
    await db.flush()


def _naive(value: str) -> datetime:
    return datetime.fromisoformat(value).replace(tzinfo=None)


async def test_seed_page_lists_runs_ranked_with_graph(test_client, async_session, pools):
    graph = {"nodes": {"start": {"layer": 0}}, "total_layers": 15}
    history = [{"node_id": "start", "igt_ms": 0, "weapons": [{"ids": [1000001], "ticks": 5}]}]
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        seed = await _seed(db, "5eed00000001")
        seed.graph_json = graph
        blind = await _add_run(db, user=a, igt_ms=1000, minute=1, zone_history=history, seed=seed)
        replay = await _add_session(
            db, b, "sprint", RunMode.SET_SEED, 1200, zone_history=history, seed=seed
        )
        obsolete = await _add_session(
            db, a, "sprint", RunMode.SET_SEED, 1500, zone_history=history, seed=seed
        )
        race = await db.get(Race, blind.race_id)
        assert race is not None and race.started_at is not None
        await db.commit()

    data = await _page(test_client, "5eed00000001")

    assert (data["public"], data["graph_json"]) == (True, graph)
    assert (data["category"], data["category_name"], data["total_layers"]) == (
        "sprint",
        "Sprint",
        15,
    )
    assert [
        (r["run_id"], r["user"]["twitch_username"], r["rank"], r["blind"], r["run_type"])
        for r in data["runs"]
    ] == [
        (str(blind.id), "a", 1, True, "race"),
        (str(replay.id), "b", 2, False, "solo"),
        (str(obsolete.id), "a", None, False, "solo"),
    ]
    assert all(r["zone_history"] == history for r in data["runs"])
    assert all(r["weapon"] == [1000000] for r in data["runs"])
    assert data["stats"] == {"best_igt_ms": 1000, "median_igt_ms": 1200, "runs": 3, "players": 2}
    origin = data["origin"]
    assert (origin["race_id"], origin["race_name"], origin["daily_date"]) == (
        str(race.id),
        race.name,
        None,
    )
    assert _naive(origin["played_at"]) == race.started_at.replace(tzinfo=None)


async def test_origin_of_a_seed_first_played_solo(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        seed = await _seed(db, "5010aa000001")
        session = await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 1000, seed=seed)
        session.created_at = BASE
        # Replays (a race and a session) started before it are no blind origin.
        replay = await _add_run(db, user=a, igt_ms=900, minute=1, mode=RunMode.SET_SEED, seed=seed)
        await _played_at(db, replay, BASE - timedelta(days=1))
        solo_replay = await _add_session(db, a, "sprint", RunMode.SET_SEED, 800, seed=seed)
        solo_replay.created_at = BASE - timedelta(days=2)
        await db.commit()

    origin = (await _page(test_client, "5010aa000001"))["origin"]

    assert (origin["race_id"], origin["race_name"], origin["daily_date"]) == (None, None, None)
    assert _naive(origin["played_at"]) == BASE.replace(tzinfo=None)


async def test_unknown_and_ambiguous_seed_ids(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        await _seed(db, "aaaaaa000001", status=SeedStatus.AVAILABLE)
        for number in ("abcdef111111", "abcdef222222"):
            await _add_run(db, user=a, igt_ms=1000, minute=1, seed=await _seed(db, number))
        await db.commit()

    unknown = await test_client.get("/api/speedrun/seeds/aaaaaa000001")
    ambiguous = await test_client.get("/api/speedrun/seeds/abcdef")

    assert (unknown.status_code, unknown.json()["detail"]) == (404, "Unknown seed")
    assert (ambiguous.status_code, ambiguous.json()["detail"]) == (409, "Ambiguous seed ID")


async def test_running_blind_race_hides_the_page(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        seed = await _seed(db, "b11d00000001")
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=seed)
        await _add_run(
            db,
            user=b,
            igt_ms=0,
            minute=2,
            kind="daily",
            race_status=RaceStatus.RUNNING,
            status=ParticipantStatus.PLAYING,
            finished=False,
            seed=seed,
        )
        await db.commit()

    data = await _page(test_client, "b11d00000001")

    assert (data["public"], data["replayable"], data["not_replayable_code"]) == (
        False,
        False,
        "in_progress",
    )
    assert data["not_replayable_reason"] == "A blind run on this seed is still in progress."
    assert (data["graph_json"], data["runs"]) == (None, [])
    assert data["stats"] == {"best_igt_ms": None, "median_igt_ms": None, "runs": 0, "players": 0}


async def test_running_set_seed_race_keeps_the_page_public(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        seed = await _seed(db, "5e7000000001")
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=seed)
        await _add_run(
            db,
            user=b,
            igt_ms=0,
            minute=2,
            mode=RunMode.SET_SEED,
            race_status=RaceStatus.RUNNING,
            status=ParticipantStatus.PLAYING,
            finished=False,
            seed=seed,
        )
        await db.commit()

    data = await _page(test_client, "5e7000000001")

    assert (data["public"], data["graph_json"]) == (True, {"nodes": {}})
    assert [r["igt_ms"] for r in data["runs"]] == [1000]
    assert data["stats"]["runs"] == 1


async def test_seed_page_of_unlisted_old_layer_count(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        old = await _seed(db, "01d000000025", pool="standard", layers=25)
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=old)
        await _add_session(db, b, "standard", RunMode.SPEEDRUN, 1100, seed=old)
        await db.commit()

    data = await _page(test_client, "01d000000025")

    assert (data["category"], data["category_name"]) == ("standard@25", "Standard (25 layers)")
    assert (data["public"], data["replayable"], data["not_replayable_code"]) == (
        True,
        False,
        "old_category",
    )
    assert data["not_replayable_reason"] == "Built for an older version of Standard."
    assert [(r["igt_ms"], r["rank"]) for r in data["runs"]] == [(1000, 1), (1100, 2)]


async def test_old_game_version_on_a_seed_read_from_the_database(
    test_client, async_session, pools, monkeypatch, tmp_path
):
    """SQLite hands the seed's creation date back naive: the cutoff comparison
    must still hold both ways."""
    monkeypatch.setattr(settings, "set_seed_min_seed_date", BASE)
    zip_path = tmp_path / "seed.zip"
    zip_path.write_bytes(b"zip")
    async with async_session() as db:
        a = await _user(db, "a")
        before = await _seed(db, "0001d0000001", folder_path=str(zip_path))
        after = await _seed(db, "0000e0000001", folder_path=str(zip_path))
        after.created_at = BASE + timedelta(days=1)
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=before)
        await _add_run(db, user=a, igt_ms=1000, minute=2, seed=after)
        await db.commit()

    old = await _page(test_client, "0001d0000001")
    new = await _page(test_client, "0000e0000001")

    assert (old["replayable"], old["not_replayable_code"], old["not_replayable_reason"]) == (
        False,
        "old_game_version",
        "Built for an older game version.",
    )
    assert (new["replayable"], new["not_replayable_code"]) == (True, None)


async def test_kept_reasons(test_client, async_session, pools):
    now = datetime.now(UTC)
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        current = await _seed(db, "c0de00000001")
        await _played_at(
            db,
            await _add_run(db, user=a, igt_ms=1000, minute=1, seed=current),
            now - timedelta(days=40),
        )
        kept = await _seed(db, "c0de00000002", status=SeedStatus.DISCARDED)
        await _played_at(
            db,
            await _add_run(db, user=a, igt_ms=1100, minute=2, seed=kept),
            now - timedelta(days=3),
        )
        db.add_all(
            [
                SeedProtection(user_id=a.id, seed_id=kept.id),
                SeedProtection(user_id=b.id, seed_id=kept.id),
            ]
        )
        # A normal community race does not count, so its seed is on no board.
        forgotten = await _seed(db, "c0de00000003", status=SeedStatus.DISCARDED)
        await _played_at(
            db,
            await _add_run(db, user=b, igt_ms=900, minute=3, mode=RunMode.NORMAL, seed=forgotten),
            now - timedelta(days=40),
        )
        await db.commit()

    assert (await _page(test_client, "c0de00000001"))["kept_reasons"] == [
        "Seed of the current Sprint pool",
        "Top 10 seed of Sprint",
    ]
    kept_page = await _page(test_client, "c0de00000002")
    assert kept_page["kept_reasons"] == [
        "Top 10 seed of Sprint",
        "Protected by 2 players",
        "Played in the last 30 days",
    ]
    assert kept_page["protected_by"] == 2
    assert (await _page(test_client, "c0de00000003"))["kept_reasons"] == []

    async with async_session() as db:
        await db.execute(delete(SeedProtection).where(SeedProtection.user_id == b.id))
        # A solo session counts as play too, even one that never finished.
        session = await _add_session(
            db,
            a,
            "sprint",
            RunMode.SET_SEED,
            0,
            status=TrainingSessionStatus.ABANDONED,
            finished_at=None,
            seed=forgotten,
        )
        session.created_at = now - timedelta(days=2)
        await db.commit()
    assert "Protected by 1 player" in (await _page(test_client, "c0de00000002"))["kept_reasons"]
    assert (await _page(test_client, "c0de00000003"))["kept_reasons"] == [
        "Played in the last 30 days"
    ]


async def test_protect_requires_a_finished_run(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        seed = await _seed(db, "f00d00000001")
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=seed)
        await _add_run(
            db,
            user=b,
            igt_ms=0,
            minute=2,
            status=ParticipantStatus.ABANDONED,
            finished=False,
            seed=seed,
        )
        await db.commit()

    url = "/api/speedrun/seeds/f00d00000001/protection"
    anonymous = await test_client.put(url)
    refused = await test_client.put(url, headers=_auth("b"))
    unknown = await test_client.put(
        "/api/speedrun/seeds/f00d99999999/protection", headers=_auth("a")
    )
    accepted = await test_client.put(url, headers=_auth("a"))

    assert anonymous.status_code == 401
    assert (refused.status_code, refused.json()["detail"]) == (
        403,
        "Only players with a finished run on this seed can protect it",
    )
    assert unknown.status_code == 404
    assert accepted.status_code == 200
    assert accepted.json() == {
        "can_protect": True,
        "protected": True,
        "protected_seeds": ["f00d00000001"],
        "protection_limit": 3,
    }


async def test_protect_limit_and_idempotence(test_client, async_session, pools):
    numbers = [f"11111100000{i}" for i in range(1, 5)]
    async with async_session() as db:
        a = await _user(db, "a")
        for minute, number in enumerate(numbers, start=1):
            await _add_run(db, user=a, igt_ms=1000, minute=minute, seed=await _seed(db, number))
        await db.commit()

    async def protect(number: str, method: str = "PUT") -> Any:
        return await test_client.request(
            method, f"/api/speedrun/seeds/{number}/protection", headers=_auth("a")
        )

    async def rows() -> int:
        async with async_session() as db:
            count = await db.scalar(select(func.count()).where(SeedProtection.user_id == a.id))
            return int(count or 0)

    for number in numbers[:3]:
        assert (await protect(number)).status_code == 200
    over = await protect(numbers[3])
    assert (over.status_code, over.json()["detail"]) == (409, "You already protect 3 seeds")

    again = await protect(numbers[1])
    assert (again.status_code, again.json()["protected"]) == (200, True)
    assert await rows() == 3

    freed = await protect(numbers[0], "DELETE")
    assert freed.status_code == 200
    assert (freed.json()["protected"], set(freed.json()["protected_seeds"])) == (
        False,
        set(numbers[1:3]),
    )
    assert (await protect(numbers[3])).status_code == 200
    assert await rows() == 3


async def test_protection_limit_message_follows_the_setting(
    test_client, async_session, pools, monkeypatch
):
    monkeypatch.setattr(settings, "seed_protection_limit", 1)
    async with async_session() as db:
        a = await _user(db, "a")
        for minute, number in enumerate(("222222000001", "222222000002"), start=1):
            await _add_run(db, user=a, igt_ms=1000, minute=minute, seed=await _seed(db, number))
        await db.commit()

    first = await test_client.put("/api/speedrun/seeds/222222000001/protection", headers=_auth("a"))
    second = await test_client.put(
        "/api/speedrun/seeds/222222000002/protection", headers=_auth("a")
    )

    assert first.json()["protection_limit"] == 1
    assert (second.status_code, second.json()["detail"]) == (409, "You already protect 1 seeds")


async def test_viewer_block(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        await _user(db, "b")
        page_seed = await _seed(db, "333333000001")
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=page_seed)
        later = await _seed(db, "333333000002")
        earlier = await _seed(db, "333333000003")
        for minute, seed in ((2, later), (3, earlier)):
            await _add_run(db, user=a, igt_ms=1000, minute=minute, seed=seed)
        # Inserted newest first: the list follows the protection dates.
        db.add(SeedProtection(user_id=a.id, seed_id=later.id, created_at=BASE + timedelta(hours=1)))
        db.add(SeedProtection(user_id=a.id, seed_id=earlier.id, created_at=BASE))
        await db.commit()

    assert (await _page(test_client, "333333000001"))["viewer"] is None
    assert (await _page(test_client, "333333000001", viewer="a"))["viewer"] == {
        "can_protect": True,
        "protected": False,
        "protected_seeds": ["333333000003", "333333000002"],
        "protection_limit": 3,
    }
    assert (await _page(test_client, "333333000002", viewer="a"))["viewer"]["protected"] is True
    assert (await _page(test_client, "333333000001", viewer="b"))["viewer"] == {
        "can_protect": False,
        "protected": False,
        "protected_seeds": [],
        "protection_limit": 3,
    }


async def test_admin_exclusion_round_trip(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        b = await _user(db, "b")
        admin = await _user(db, "admin")
        admin.role = UserRole.ADMIN
        broken = await _seed(db, "badbad000001")
        await _add_run(db, user=a, igt_ms=1000, minute=1, seed=broken)
        await _add_run(db, user=b, igt_ms=1100, minute=2, seed=await _seed(db, "900d00000001"))
        await db.commit()

    url = "/api/admin/seeds/badbad000001/set-seed-exclusion"

    async def board(sub: str = "set") -> list[str]:
        data = (await test_client.get(f"/api/stats/speedrun/sprint?sub={sub}")).json()
        return [r["user"]["twitch_username"] for r in data["runs"]]

    async def excluded_by() -> Any:
        async with async_session() as db:
            return await db.scalar(
                select(Seed.set_seed_excluded_by_id).where(Seed.seed_number == "badbad000001")
            )

    assert await board() == ["a", "b"]  # now cached

    forbidden = await test_client.put(url, json={"reason": "Broken warp"}, headers=_auth("a"))
    blank = await test_client.put(url, json={"reason": "   "}, headers=_auth("admin"))
    too_long = await test_client.put(url, json={"reason": "x" * 501}, headers=_auth("admin"))
    unknown = await test_client.put(
        "/api/admin/seeds/badbad999999/set-seed-exclusion",
        json={"reason": "Broken warp"},
        headers=_auth("admin"),
    )
    assert (forbidden.status_code, blank.status_code, too_long.status_code) == (403, 422, 422)
    assert (unknown.status_code, unknown.json()["detail"]) == (404, "Unknown seed")

    excluded = await test_client.put(
        url, json={"reason": "  Broken warp  "}, headers=_auth("admin")
    )
    assert excluded.status_code == 204
    page = await _page(test_client, "badbad000001")
    assert (page["replayable"], page["not_replayable_code"], page["excluded_reason"]) == (
        False,
        "excluded",
        "Broken warp",
    )
    assert page["not_replayable_reason"] == "Excluded from Set Seed: Broken warp"
    assert await excluded_by() == admin.id
    assert await board() == ["b"]
    assert await board("random") == ["a", "b"]

    restored = await test_client.delete(url, headers=_auth("admin"))
    assert restored.status_code == 204
    page = await _page(test_client, "badbad000001")
    assert (page["excluded_reason"], page["not_replayable_code"]) == (None, "purged")
    assert await excluded_by() is None
    assert await board() == ["a", "b"]


async def test_race_and_session_responses_carry_kind(test_client, async_session, pools):
    async with async_session() as db:
        a = await _user(db, "a")
        replay = await _add_run(db, user=a, igt_ms=1000, minute=1, mode=RunMode.SET_SEED)
        normal = await _add_run(db, user=a, igt_ms=1000, minute=2, mode=RunMode.NORMAL)
        ranked = await _add_session(db, a, "sprint", RunMode.SPEEDRUN, 1000)
        practice = await _add_session(db, a, "sprint", RunMode.NORMAL, 1000)
        await db.commit()

    race_modes = {r["id"]: r["mode"] for r in (await test_client.get("/api/races")).json()["races"]}
    assert race_modes == {str(replay.race_id): "set_seed", str(normal.race_id): "normal"}
    detail = (await test_client.get(f"/api/races/{replay.race_id}")).json()
    assert detail["mode"] == "set_seed"

    sessions = (await test_client.get("/api/training", headers=_auth("a"))).json()
    assert {s["id"]: s["mode"] for s in sessions} == {
        str(ranked.id): "speedrun",
        str(practice.id): "normal",
    }
    assert (await test_client.get(f"/api/training/{ranked.id}")).json()["mode"] == "speedrun"
