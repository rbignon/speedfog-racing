"""tools/relay_bot.py: what the console reads and writes in the database, on relay race rows."""

from __future__ import annotations

import importlib.util
import sys
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload

from speedfog_racing import database as db_module
from speedfog_racing.database import Base
from speedfog_racing.models import Participant, RelayTeam, User
from speedfog_racing.services.relay import relay_cap
from tests.relay_fixtures import (
    BOSS_NODE,
    PROGRESS_TOTAL_LAYERS,
    SECOND_FOG_FLAG,
    START_NODE,
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


async def _users(db, n: int) -> list[User]:
    users = [
        User(twitch_id=f"rb{i}", twitch_username=f"rb{i}", api_token=f"rbt{i}") for i in range(n)
    ]
    db.add_all(users)
    await db.flush()
    return users


async def _setup_race(maker) -> str:
    """A relay race in setup, teams of two, with no team yet; rb0 organizes it."""
    async with maker() as db:
        users = await _users(db, 6)
        race = await make_relay_race(db, users[0], team_size=2, teams=[], graph=progress_graph())
        return str(race.id)


async def _teams(maker, race_id: str) -> dict[str, tuple[set[str], str | None]]:
    """Each team by name: its members and its first runner."""
    async with maker() as db:
        teams = (
            (
                await db.execute(
                    select(RelayTeam)
                    .where(RelayTeam.race_id == uuid.UUID(race_id))
                    .options(selectinload(RelayTeam.members).selectinload(Participant.user))
                )
            )
            .scalars()
            .all()
        )
    return {
        t.name: (
            {m.user.twitch_username for m in t.members},
            next((m.user.twitch_username for m in t.members if m.id == t.first_runner_id), None),
        )
        for t in teams
    }


async def test_status_names_each_teams_holder_and_members(bot_session, capsys):
    """The console opens its own sessions: nothing it prints may rest on a row
    another session loaded (a lazy load fails under asyncio)."""
    async with bot_session() as db:
        users = await _users(db, 5)
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


@pytest.mark.parametrize(
    "launched_ms_before_the_bot",
    [600_000, -60_000],  # the game launched before the bot started, then after
)
async def test_event_flag_ids_never_take_the_next_id_of_a_recorded_mod(
    bot_session, launched_ms_before_the_bot
):
    """The server drops a fog flag whose id the team already recorded: the bot's
    flags must not take the ids a game's mod sends next (one more than its last)."""
    mod_id = time.time_ns() // 1_000_000 - launched_ms_before_the_bot
    async with bot_session() as db:
        users = await _users(db, 3)
        race = await make_relay_race(
            db, users[0], team_size=2, teams=[users[1:3]], graph=progress_graph()
        )
        await run_relay_race(db, race, started_at=datetime.now(UTC))
        race.relay_teams[0].zone_history = [
            {"node_id": START_NODE, "igt_ms": 0, "type": "spawn"},
            {"node_id": BOSS_NODE, "igt_ms": 70_000, "type": "fog", "message_id": mod_id},
        ]
        await db.commit()
        race_id = str(race.id)
        team_id = str(race.relay_teams[0].id)

    console = rb.Console(race_id, "ws://unused", [("Team 1", ["rb1", "rb2"])], rb.FAKE_STATE)
    await console.load()
    for bot in console.bots.values():
        bot.team_id = team_id  # set by the RelayInfo of auth_ok, and no socket is open
    sent: list[int] = []

    async def capture(bot, payload):
        sent.append(payload["message_id"])
        return True

    console.send = capture
    # Two bots of one team share its history: never the same id twice.
    for name in ("rb1", "rb2", "rb1"):
        await console.flag(console.bots[name], SECOND_FOG_FLAG)

    assert len(set(sent)) == 3
    # Neither the recorded id nor the ones its mod sends next.
    assert not set(sent) & set(range(mod_id, mod_id + 1_000))


async def test_load_creates_the_named_teams_and_places_the_bots(bot_session):
    race_id = await _setup_race(bot_session)

    console = rb.Console(
        race_id,
        "ws://unused",
        [("Alpha", ["rb1", "rb2"]), ("Beta", ["rb3", "rb4"])],
        rb.FAKE_STATE,
    )
    await console.load()

    # The first bot placed in a team it creates starts the team's run.
    assert await _teams(bot_session, race_id) == {
        "Alpha": ({"rb1", "rb2"}, "rb1"),
        "Beta": ({"rb3", "rb4"}, "rb3"),
    }
    assert {b.name: b.team_name for b in console.bots.values()} == {
        "rb1": "Alpha",
        "rb2": "Alpha",
        "rb3": "Beta",
        "rb4": "Beta",
    }


async def test_a_refused_placement_keeps_the_bots_placed_before_it(bot_session):
    race_id = await _setup_race(bot_session)

    too_many = rb.Console(race_id, "ws://unused", [("Alpha", ["rb1", "rb2", "rb3"])], rb.FAKE_STATE)
    with pytest.raises(SystemExit, match="Team is full"):
        await too_many.load()
    assert await _teams(bot_session, race_id) == {"Alpha": ({"rb1", "rb2"}, "rb1")}

    # A second start places the rest and finds the others where they were.
    again = rb.Console(
        race_id,
        "ws://unused",
        [("Alpha", ["rb1", "rb2"]), ("Beta", ["rb3", "rb4"])],
        rb.FAKE_STATE,
    )
    await again.load()
    assert await _teams(bot_session, race_id) == {
        "Alpha": ({"rb1", "rb2"}, "rb1"),
        "Beta": ({"rb3", "rb4"}, "rb3"),
    }
    assert set(again.bots) == {"rb1", "rb2", "rb3", "rb4"}
