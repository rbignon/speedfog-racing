"""tools/relay_bot.py: what the console reads from the database, on a relay race's rows."""

from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing import database as db_module
from speedfog_racing.database import Base
from speedfog_racing.models import User
from speedfog_racing.services.relay import relay_cap
from tests.relay_fixtures import (
    PROGRESS_TOTAL_LAYERS,
    make_relay_race,
    progress_graph,
    run_relay_race,
)

_SCRIPT = Path(__file__).resolve().parents[2] / "tools" / "relay_bot.py"
_spec = importlib.util.spec_from_file_location("relay_bot", _SCRIPT)
assert _spec is not None and _spec.loader is not None
rb = importlib.util.module_from_spec(_spec)
sys.modules["relay_bot"] = rb  # dataclasses look their module up
_path = list(sys.path)
_spec.loader.exec_module(rb)
sys.path[:] = _path  # the tool puts tools/ first for its own imports: not for the suite's

pytestmark = pytest.mark.asyncio

CAP = relay_cap(PROGRESS_TOTAL_LAYERS, 2)


@pytest.fixture
async def bot_session(monkeypatch):
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    maker = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    monkeypatch.setattr(db_module, "async_session_maker", maker)
    yield maker
    await engine.dispose()


async def test_status_names_each_teams_holder_and_members(bot_session, capsys):
    """The console opens its own sessions: nothing it prints may rest on a row
    another session loaded (a lazy load fails under asyncio)."""
    async with bot_session() as db:
        users = [
            User(twitch_id=f"rb{i}", twitch_username=f"rb{i}", api_token=f"rbt{i}")
            for i in range(5)
        ]
        db.add_all(users)
        await db.flush()
        race = await make_relay_race(
            db, users[0], team_size=2, teams=[users[1:3], users[3:5]], graph=progress_graph()
        )
        await run_relay_race(db, race, started_at=datetime.now(UTC))
        race_id = str(race.id)

    console = rb.Console(
        race_id,
        "ws://unused",
        [("Team 1", ["rb1", "rb2"]), ("Team 2", ["rb3", "rb4"])],
        rb.FAKE_STATE,
    )
    await console.load()
    await console.status()

    # Sorted: the fixture's teams and members share one creation time, so the
    # order they are listed in is not defined.
    lines = capsys.readouterr().out.splitlines()
    holders = [line.split("holder ")[1].split()[0] for line in lines if "holder " in line]
    assert sorted(holders) == ["rb1", "rb3"]
    members = [line.split() for line in lines if " zones" in line]
    # No socket was opened, so every bot reads offline.
    assert sorted((m[0], m[2], m[-1]) for m in members) == [
        (name, f"0/{CAP}", "offline") for name in ("rb1", "rb2", "rb3", "rb4")
    ]
