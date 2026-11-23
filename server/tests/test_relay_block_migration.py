"""The migration that recomputes seeds.relay for the 4.16 relay block."""

import importlib.util
from pathlib import Path

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import Seed
from tests.relay_fixtures import RELAY_BLOCK

pytestmark = pytest.mark.asyncio

_MIGRATION = next(
    (Path(__file__).resolve().parents[1] / "alembic" / "versions").glob(
        "*_recompute_seeds_relay_for_the_4_16_block.py"
    )
)


@pytest.fixture
async def rb_session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


def _load():
    spec = importlib.util.spec_from_file_location("relay_block_migration", _MIGRATION)
    assert spec is not None and spec.loader is not None
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    return migration


async def test_upgrade_keeps_only_the_4_16_block_and_downgrade_restores_the_old_rule(rb_session):
    migration = _load()
    old_block = {k: v for k, v in RELAY_BLOCK.items() if k not in ("loot", "roundtable_warp_flag")}
    graphs = {
        "new": {"nodes": {}, "relay": dict(RELAY_BLOCK)},
        "no_boss": {"nodes": {}, "relay": {**RELAY_BLOCK, "loot": {}}},
        "old": {"nodes": {}, "relay": old_block},
        "none": {"nodes": {}},
    }
    async with rb_session() as db:
        for name, graph in graphs.items():
            db.add(
                Seed(
                    seed_number=f"rb_{name}",
                    pool_name="standard",
                    graph_json=graph,
                    relay=name != "none",  # what the old rule stored
                    total_layers=5,
                    folder_path=f"/test/rb_{name}",
                )
            )
        await db.commit()

        async def relay_column() -> dict[str, bool]:
            rows = await db.execute(select(Seed.seed_number, Seed.relay))
            return dict(rows.all())

        await db.execute(text(migration._UPGRADE_SQLITE))
        await db.commit()
        db.expire_all()
        assert await relay_column() == {
            "rb_new": True,
            "rb_no_boss": True,
            "rb_old": False,
            "rb_none": False,
        }

        await db.execute(text(migration._DOWNGRADE_SQLITE))
        await db.commit()
        db.expire_all()
        assert await relay_column() == {
            "rb_new": True,
            "rb_no_boss": True,
            "rb_old": True,
            "rb_none": False,
        }
