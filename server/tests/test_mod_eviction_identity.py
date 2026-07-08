"""Mod-connection eviction must not drop a newer connection.

When a room broadcast fails on a stale (ghost) mod connection, the room evicts
it. But between snapshotting the connection and running the failing send, the
mod can reconnect: ``connect_mod`` replaces the entry with a fresh connection.
The eviction must then leave the fresh connection in place, else the live mod
stops receiving room broadcasts (leaderboard, race_start, chat) until it
reconnects again. These tests reproduce that interleaving deterministically.
"""

import uuid
from unittest.mock import AsyncMock

import pytest

from speedfog_racing.websocket.race.manager import ConnectionManager, ModConnection


class _SwapThenFailWS:
    """A websocket whose ``send_text`` swaps the room entry, then raises.

    Simulates a ghost connection being replaced by a reconnect while its own
    send is still in flight.
    """

    def __init__(self, swap):
        self._swap = swap

    async def send_text(self, message: str) -> None:
        self._swap()
        raise RuntimeError("connection dropped")


def _room_with_ghost(mgr: ConnectionManager):
    race_id = uuid.uuid4()
    participant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    room = mgr.get_or_create_room(race_id)
    replacement = ModConnection(
        websocket=AsyncMock(), participant_id=participant_id, user_id=user_id
    )

    def swap() -> None:
        room.mods[participant_id] = replacement

    ghost = ModConnection(
        websocket=_SwapThenFailWS(swap), participant_id=participant_id, user_id=user_id
    )
    room.mods[participant_id] = ghost
    return race_id, participant_id, user_id, room, replacement


@pytest.mark.asyncio
async def test_broadcast_to_mods_keeps_replacement_connection():
    mgr = ConnectionManager()
    _race_id, participant_id, _user_id, room, replacement = _room_with_ghost(mgr)

    await room.broadcast_to_mods("payload")

    assert room.mods.get(participant_id) is replacement


@pytest.mark.asyncio
async def test_send_to_mod_keeps_replacement_connection():
    mgr = ConnectionManager()
    _race_id, participant_id, _user_id, room, replacement = _room_with_ghost(mgr)

    ok = await room.send_to_mod(participant_id, "payload")

    assert ok is False  # the ghost send failed
    assert room.mods.get(participant_id) is replacement


@pytest.mark.asyncio
async def test_daily_streak_update_keeps_replacement_connection():
    mgr = ConnectionManager()
    race_id, participant_id, user_id, room, replacement = _room_with_ghost(mgr)

    await mgr.send_daily_streak_update_to_user(race_id, user_id, current=1, best=1, freeze_count=0)

    assert room.mods.get(participant_id) is replacement
