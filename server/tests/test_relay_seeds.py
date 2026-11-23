"""Relay seeds: the graph.json block, the scanned column, the draw filter, the pool count."""

import importlib.util
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base, get_db
from speedfog_racing.main import app
from speedfog_racing.models import Race, Seed, SeedStatus, User, UserRole
from speedfog_racing.services.relay import relay_flags, relay_warp_flag, seed_has_relay
from speedfog_racing.services.seed_service import assign_seed_to_race, get_available_seed
from speedfog_racing.websocket.schemas import RelayFlags
from tests import relay_fixtures as _relay_fixtures
from tests.relay_fixtures import RELAY_BLOCK

relay_races_on = _relay_fixtures.relay_races_on

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "5b9c2e7a4d13_add_relay_to_seeds.py"
)


def _relay_graph() -> dict:
    return {"total_layers": 5, "nodes": [], "relay": RELAY_BLOCK}


def _plain_graph() -> dict:
    return {"total_layers": 5, "nodes": []}


@pytest.mark.parametrize(
    "block, expected",
    [
        (dict(RELAY_BLOCK), True),
        ({k: v for k, v in RELAY_BLOCK.items() if k != "loot"}, False),  # --no-build, or 4.15
        ({k: v for k, v in RELAY_BLOCK.items() if k != "roundtable_warp_flag"}, False),
        ({**RELAY_BLOCK, "roundtable_warp_flag": "1050290504"}, False),
        ({**RELAY_BLOCK, "loot": []}, False),
        ({**RELAY_BLOCK, "loot": {}}, True),  # a seed with no boss
        ({}, False),
        ("x", False),
        (None, False),
    ],
)
def test_only_a_4_16_block_makes_a_relay_seed(block, expected):
    graph = {"nodes": {}} if block is None else {"nodes": {}, "relay": block}
    assert seed_has_relay(graph) is expected


def test_relay_flags_are_the_integers_of_the_block_without_the_count():
    flags = relay_flags({"relay": dict(RELAY_BLOCK)})
    assert "loot" not in flags and "warp_flag_count" not in flags
    assert RelayFlags(**flags).travel_lock_flag == 1050290503
    assert relay_flags(_plain_graph()) is None


def test_the_warp_before_any_gate_is_the_chapel_warp():
    flags = relay_flags({"relay": dict(RELAY_BLOCK)})
    assert relay_warp_flag(flags, None) == 1050290501
    assert relay_warp_flag(flags, 1050294007) == 1050290517


@pytest.fixture
async def rl_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


@pytest.fixture
def rl_client(rl_session):
    async def override_get_db():
        async with rl_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
    app.dependency_overrides.clear()


def _seed(suffix: str, graph: dict, status: SeedStatus = SeedStatus.AVAILABLE) -> Seed:
    return Seed(
        seed_number=f"rl_{suffix}",
        pool_name="standard",
        graph_json=graph,
        relay=seed_has_relay(graph),
        total_layers=5,
        folder_path=f"/test/rl_{suffix}",
        status=status,
    )


def _relay_race(organizer: User) -> Race:
    return Race(name="Relay", organizer_id=organizer.id, relay_team_size=3)


@pytest.fixture
async def rl_organizer(rl_session):
    async with rl_session() as db:
        user = User(
            twitch_id="org_rl",
            twitch_username="organizer_rl",
            twitch_display_name="Organizer RL",
            api_token="org_rl_token",
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        await db.commit()
        return user


@pytest.mark.asyncio
async def test_scan_sets_relay_from_the_graph(rl_session, tmp_path, monkeypatch):
    from speedfog_racing.services import seed_service

    from .test_seed_service import _create_seed_zip

    pool_dir = tmp_path / "standard"
    pool_dir.mkdir()
    _create_seed_zip(pool_dir, "seed_with", _relay_graph())
    _create_seed_zip(pool_dir, "seed_without", _plain_graph())
    monkeypatch.setattr(seed_service.settings, "seeds_pool_dir", str(tmp_path))

    async with rl_session() as db:
        assert await seed_service.scan_pool(db, "standard") == 2
        seeds = (await db.execute(select(Seed))).scalars().all()
    assert {s.seed_number: s.relay for s in seeds} == {"with": True, "without": False}


@pytest.mark.asyncio
async def test_relay_draw_takes_only_relay_seeds(rl_session):
    async with rl_session() as db:
        relay_seed = _seed("relay", _relay_graph())
        db.add_all([relay_seed, *(_seed(f"p{i}", _plain_graph()) for i in range(5))])
        await db.commit()
        for _ in range(10):
            drawn = await get_available_seed(db, "standard", require_relay=True)
            assert drawn is not None and drawn.id == relay_seed.id


@pytest.mark.asyncio
async def test_relay_draw_fails_without_a_relay_seed(rl_session, rl_organizer):
    async with rl_session() as db:
        db.add(_seed("plain", _plain_graph()))
        race = _relay_race(rl_organizer)
        db.add(race)
        await db.commit()
        with pytest.raises(ValueError, match="No relay seed available in pool 'standard'"):
            await assign_seed_to_race(db, race, "standard", allow_seen=True)
        plain = (await db.execute(select(Seed))).scalar_one()
        assert plain.status == SeedStatus.AVAILABLE


@pytest.mark.asyncio
async def test_relay_race_is_assigned_a_relay_seed(rl_session, rl_organizer):
    async with rl_session() as db:
        relay_seed = _seed("relay", _relay_graph())
        db.add_all([relay_seed, _seed("plain", _plain_graph())])
        race = _relay_race(rl_organizer)
        db.add(race)
        await db.commit()
        seed = await assign_seed_to_race(db, race, "standard", allow_seen=True)
        assert seed.id == relay_seed.id


@pytest.mark.asyncio
async def test_pools_endpoint_counts_relay_seeds(rl_client, rl_session, relay_races_on):
    async with rl_session() as db:
        db.add_all(
            [
                _seed("a", _relay_graph()),
                _seed("b", _relay_graph(), SeedStatus.SEEN),
                _seed("c", _relay_graph(), SeedStatus.CONSUMED),
                _seed("d", _plain_graph()),
            ]
        )
        await db.commit()

    async with rl_client as client:
        resp = await client.get("/api/pools?type=race")
    assert resp.status_code == 200, resp.text
    assert resp.json()["standard"]["relay_available"] == 2


@pytest.mark.asyncio
async def test_pools_offer_no_relay_seed_while_relay_races_are_off(
    rl_client, rl_session, monkeypatch
):
    from speedfog_racing.config import settings

    monkeypatch.setattr(settings, "relay_races_enabled", False)
    async with rl_session() as db:
        db.add(_seed("a", _relay_graph()))
        await db.commit()

    async with rl_client as client:
        resp = await client.get("/api/pools?type=race")
    assert resp.status_code == 200, resp.text
    assert (resp.json()["standard"]["available"], resp.json()["standard"]["relay_available"]) == (
        1,
        0,
    )


@pytest.mark.asyncio
async def test_backfill_marks_seeds_carrying_the_block(rl_session):
    spec = importlib.util.spec_from_file_location("relay_seeds_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    graphs = {
        "block": _relay_graph(),
        "empty": {**_plain_graph(), "relay": {}},
        "not_object": {**_plain_graph(), "relay": "x"},
        "plain": _plain_graph(),
    }
    async with rl_session() as db:
        for name, graph in graphs.items():
            seed = _seed(name, graph)
            seed.relay = False
            db.add(seed)
        await db.commit()
        await db.execute(text(migration._BACKFILL_SQLITE))
        await db.commit()
        rows = await db.execute(select(Seed.seed_number, Seed.relay))
        assert {number: flag for number, flag in rows} == {
            "rl_block": True,
            "rl_empty": False,
            "rl_not_object": False,
            "rl_plain": False,
        }
