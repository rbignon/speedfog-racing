"""The migration that clears race_items on the seeds older than graph.json 4.12."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Seed, SeedStatus

_MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "24e50b1ae2f9_clear_race_items_on_pre_4_12_seeds.py"
)


def _load() -> ModuleType:
    spec = importlib.util.spec_from_file_location("race_items_seeds_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


migration = _load()

PLUGIN = {"race_items": {"enabled": True}}
V2 = {
    "goods": {"race_item": {"goods_id": 1450801}},
    "items": {"hammer": {"name": "Hammer", "goods": "race_item"}},
}
V1 = {"banana": {"name": "Banana", "goods_id": 1450804, "use_flag": 1050290104}}

GRAPHS = {
    "v2": {"plugins": PLUGIN, "race_items": V2},
    "v1": {"plugins": PLUGIN, "race_items": V1},
    "no_items": {"plugins": PLUGIN, "race_items": {"goods": V2["goods"], "items": {}}},
    "goods_not_an_object": {"plugins": PLUGIN, "race_items": {**V2, "goods": []}},
    "plugin_off": {"plugins": {"race_items": {"enabled": False}}, "race_items": V2},
    "no_plugin": {"race_items": V2},
}


@pytest.mark.parametrize(
    "name,expected",
    [
        ("v2", True),
        ("v1", False),
        ("no_items", False),
        ("goods_not_an_object", False),
        ("plugin_off", False),
        ("no_plugin", False),
    ],
)
def test_only_the_4_12_shape_counts(name: str, expected: bool) -> None:
    assert migration.has_4_12_catalog(GRAPHS[name]) is expected


@pytest.fixture
async def engine():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


async def _flags(engine: AsyncEngine) -> dict[str, bool]:
    async with AsyncSession(engine) as db:
        rows = await db.execute(select(Seed.seed_number, Seed.race_items))
        return {number: flag for number, flag in rows}


async def test_flagged_seeds_without_the_4_12_catalog_are_cleared(
    engine: AsyncEngine, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Batches of 2 over 7 flagged seeds: the reads and the update span several.
    monkeypatch.setattr(migration, "BATCH_SIZE", 2)
    async with AsyncSession(engine) as db:
        for name, graph in [*GRAPHS.items(), ("v2_bis", GRAPHS["v2"])]:
            db.add(
                Seed(
                    seed_number=name,
                    pool_name="experimental",
                    graph_json=graph,
                    race_items=True,
                    total_layers=5,
                    folder_path=f"/test/{name}",
                    status=SeedStatus.AVAILABLE,
                )
            )
        # An unflagged seed stays unflagged, whatever its graph.
        db.add(
            Seed(
                seed_number="plain",
                pool_name="standard",
                graph_json={"total_layers": 5},
                total_layers=5,
                folder_path="/test/plain",
                status=SeedStatus.AVAILABLE,
            )
        )
        await db.commit()

    async with engine.begin() as conn:
        cleared = await conn.run_sync(migration.clear_pre_4_12_seeds)

    assert cleared == 5
    assert await _flags(engine) == {
        "v2": True,
        "v2_bis": True,
        "v1": False,
        "no_items": False,
        "goods_not_an_object": False,
        "plugin_off": False,
        "no_plugin": False,
        "plain": False,
    }
