"""Tests for the per-room ghost snapshot shared by async-race heartbeats.

On races that project ghosts (dailies, event qualifiers), every playing mod's
1 Hz ``status_update`` unicasts a projected leaderboard built from the whole
field. ``RaceRoom.ghost_participants`` lets those heartbeats share one load of
the field instead of reloading every participant on each message.
"""

import asyncio
import uuid
from typing import Any

import pytest

import speedfog_racing.websocket.race.manager as manager_module
from speedfog_racing.websocket.race.manager import (
    GHOST_SNAPSHOT_TTL,
    ConnectionManager,
    RaceRoom,
)


class Loader:
    """Counts loads; ``gate`` holds them until the test opens it."""

    def __init__(self, *, gate: asyncio.Event | None = None, error: Exception | None = None):
        self.calls = 0
        self.started = asyncio.Event()
        self._gate = gate
        self._error = error

    async def __call__(self) -> list[Any]:
        self.calls += 1
        call = self.calls
        self.started.set()
        if self._gate is not None:
            await self._gate.wait()
        if self._error is not None:
            raise self._error
        return [f"field-{call}"]


@pytest.fixture
def clock(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    now = [1000.0]
    monkeypatch.setattr(manager_module, "monotonic", lambda: now[0])
    return now


async def test_snapshot_is_reused_within_its_ttl(clock: list[float]) -> None:
    room = RaceRoom(race_id=uuid.uuid4())
    load = Loader()

    first = await room.ghost_participants(load)
    clock[0] += GHOST_SNAPSHOT_TTL - 0.1
    second = await room.ghost_participants(load)

    assert load.calls == 1
    assert second == first


async def test_snapshot_reloads_once_expired(clock: list[float]) -> None:
    room = RaceRoom(race_id=uuid.uuid4())
    load = Loader()

    await room.ghost_participants(load)
    clock[0] += GHOST_SNAPSHOT_TTL
    refreshed = await room.ghost_participants(load)

    assert load.calls == 2
    assert refreshed == ["field-2"]


async def test_snapshot_age_counts_from_the_start_of_its_load(clock: list[float]) -> None:
    room = RaceRoom(race_id=uuid.uuid4())
    gate = asyncio.Event()
    load = Loader(gate=gate)

    loading = asyncio.create_task(room.ghost_participants(load))
    await load.started.wait()
    clock[0] += 2.0  # a slow load
    gate.set()
    await loading
    clock[0] += GHOST_SNAPSHOT_TTL - 2.0

    assert await room.ghost_participants(load) == ["field-2"]


async def test_concurrent_heartbeats_share_one_load(clock: list[float]) -> None:
    room = RaceRoom(race_id=uuid.uuid4())
    gate = asyncio.Event()
    load = Loader(gate=gate)

    waiting = [asyncio.create_task(room.ghost_participants(load)) for _ in range(5)]
    await load.started.wait()
    gate.set()
    results = await asyncio.gather(*waiting)

    assert load.calls == 1
    assert all(r == ["field-1"] for r in results)


async def test_a_failed_load_reaches_every_waiter_and_is_retried_next_time(
    clock: list[float],
) -> None:
    room = RaceRoom(race_id=uuid.uuid4())
    gate = asyncio.Event()
    failing = Loader(gate=gate, error=RuntimeError("db down"))

    waiting = [asyncio.create_task(room.ghost_participants(failing)) for _ in range(3)]
    await failing.started.wait()
    gate.set()
    results = await asyncio.gather(*waiting, return_exceptions=True)

    assert failing.calls == 1
    assert all(isinstance(r, RuntimeError) for r in results)
    assert await room.ghost_participants(Loader()) == ["field-1"]


async def test_a_cancelled_waiter_does_not_cancel_the_shared_load(clock: list[float]) -> None:
    room = RaceRoom(race_id=uuid.uuid4())
    gate = asyncio.Event()
    load = Loader(gate=gate)

    first = asyncio.create_task(room.ghost_participants(load))
    second = asyncio.create_task(room.ghost_participants(load))
    await load.started.wait()
    first.cancel()
    gate.set()

    assert await second == ["field-1"]
    assert load.calls == 1


async def test_invalidated_snapshot_reloads(clock: list[float]) -> None:
    room = RaceRoom(race_id=uuid.uuid4())
    load = Loader()

    await room.ghost_participants(load)
    room.invalidate_ghosts()
    refreshed = await room.ghost_participants(load)

    assert load.calls == 2
    assert refreshed == ["field-2"]


async def test_a_load_overtaken_by_an_invalidation_is_not_used(clock: list[float]) -> None:
    """The progression that invalidated it just broadcast a fresh projection to
    every mod: answering a heartbeat with the older field would step a ghost back."""
    room = RaceRoom(race_id=uuid.uuid4())
    gate = asyncio.Event()
    load = Loader(gate=gate)

    loading = asyncio.create_task(room.ghost_participants(load))
    await load.started.wait()
    room.invalidate_ghosts()
    gate.set()

    assert await loading is None
    assert await room.ghost_participants(Loader()) == ["field-1"]


async def test_leaderboard_broadcast_invalidates_the_snapshot(clock: list[float]) -> None:
    """A real progression broadcasts a leaderboard: the next heartbeat must see it."""
    mgr = ConnectionManager()
    race_id = uuid.uuid4()
    room = mgr.get_or_create_room(race_id)
    load = Loader()
    await room.ghost_participants(load)

    await mgr.broadcast_leaderboard(race_id, [], project_ghosts=True)

    assert await room.ghost_participants(load) == ["field-2"]
