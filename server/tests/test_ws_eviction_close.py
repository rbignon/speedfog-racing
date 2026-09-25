"""A connection evicted from its room after a failed send must be closed.

Eviction drops the connection from the room, but its handler's heartbeat keeps
the socket alive: left open, the client would silently stop receiving
broadcasts (frozen web leaderboard, mod shown as disconnected) until a manual
reload. Closing with a code below 4000 makes both the web client and the mod
reconnect and resync.
"""

import asyncio
import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from speedfog_racing.websocket import handler as handler_module
from speedfog_racing.websocket.race import spectator as race_spectator
from speedfog_racing.websocket.race.manager import (
    ConnectionManager,
    ModConnection,
    SpectatorConnection,
)
from speedfog_racing.websocket.training.manager import (
    TrainingModConnection,
    TrainingRoom,
    TrainingSpectatorConnection,
)

RECONNECT_BELOW = 4000  # web and mod clients treat 4xxx as permanent


class _FakeWS:
    def __init__(self, *, fail: bool = False, hang_on_close: bool = False) -> None:
        self.fail = fail
        self.hang_on_close = hang_on_close
        self.sent: list[str] = []
        self.close_codes: list[int] = []

    async def send_text(self, message: str) -> None:
        if self.fail:
            raise RuntimeError("send failed")
        self.sent.append(message)

    async def close(self, code: int = 1000, reason: str = "") -> None:
        self.close_codes.append(code)
        if self.hang_on_close:
            await asyncio.Event().wait()  # a peer that never completes the handshake


async def _drain() -> None:
    """Let background close tasks run."""
    for _ in range(3):
        await asyncio.sleep(0)


def _assert_closed_for_reconnect(ws: _FakeWS) -> None:
    assert len(ws.close_codes) == 1
    assert ws.close_codes[0] < RECONNECT_BELOW


@pytest.mark.asyncio
async def test_failed_spectator_is_evicted_and_closed():
    room = ConnectionManager().get_or_create_room(uuid.uuid4())
    healthy, broken = _FakeWS(), _FakeWS(fail=True)
    healthy_conn = SpectatorConnection(websocket=healthy)  # type: ignore[arg-type]
    broken_conn = SpectatorConnection(websocket=broken)  # type: ignore[arg-type]
    room.spectators = {c.connection_id: c for c in (healthy_conn, broken_conn)}

    await room.broadcast_to_spectators("payload")
    await _drain()

    assert list(room.spectators) == [healthy_conn.connection_id]
    _assert_closed_for_reconnect(broken)
    assert healthy.close_codes == []
    assert healthy.sent == ["payload"]


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["broadcast_chat_participants", "broadcast_chat_public"])
async def test_failed_chat_recipient_is_evicted_and_closed(method, monkeypatch):
    from speedfog_racing.websocket.race import manager as manager_module

    monkeypatch.setattr(manager_module, "can_read_public_chat", lambda *a, **k: True)
    room = ConnectionManager().get_or_create_room(uuid.uuid4())
    broken = _FakeWS(fail=True)
    conn = SpectatorConnection(websocket=broken, role="participant")  # type: ignore[arg-type]
    room.spectators = {conn.connection_id: conn}

    if method == "broadcast_chat_public":
        await room.broadcast_chat_public("payload", SimpleNamespace())  # type: ignore[arg-type]
    else:
        await room.broadcast_chat_participants("payload")
    await _drain()

    assert room.spectators == {}
    _assert_closed_for_reconnect(broken)


@pytest.mark.asyncio
async def test_failed_mod_broadcast_evicts_and_closes():
    room = ConnectionManager().get_or_create_room(uuid.uuid4())
    broken = _FakeWS(fail=True)
    pid = uuid.uuid4()
    room.mods[pid] = ModConnection(websocket=broken, participant_id=pid, user_id=uuid.uuid4())  # type: ignore[arg-type]

    await room.broadcast_to_mods("payload")
    await _drain()

    assert room.mods == {}
    _assert_closed_for_reconnect(broken)


@pytest.mark.asyncio
async def test_failed_mod_unicast_evicts_and_closes():
    room = ConnectionManager().get_or_create_room(uuid.uuid4())
    broken = _FakeWS(fail=True)
    pid = uuid.uuid4()
    room.mods[pid] = ModConnection(websocket=broken, participant_id=pid, user_id=uuid.uuid4())  # type: ignore[arg-type]

    assert await room.send_to_mod(pid, "payload") is False
    await _drain()

    assert room.mods == {}
    _assert_closed_for_reconnect(broken)


@pytest.mark.asyncio
async def test_failed_daily_streak_recipients_are_closed():
    mgr = ConnectionManager()
    race_id, user_id, pid = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    room = mgr.get_or_create_room(race_id)
    mod_ws, spec_ws = _FakeWS(fail=True), _FakeWS(fail=True)
    room.mods[pid] = ModConnection(websocket=mod_ws, participant_id=pid, user_id=user_id)  # type: ignore[arg-type]
    spec = SpectatorConnection(websocket=spec_ws, user_id=user_id)  # type: ignore[arg-type]
    room.spectators = {spec.connection_id: spec}

    await mgr.send_daily_streak_update_to_user(race_id, user_id, current=1, best=1, freeze_count=0)
    await _drain()

    _assert_closed_for_reconnect(mod_ws)
    _assert_closed_for_reconnect(spec_ws)


@pytest.mark.asyncio
async def test_replaced_mod_is_not_closed_by_ghost_eviction():
    """The ghost's failed send must not close the reconnect that replaced it."""
    room = ConnectionManager().get_or_create_room(uuid.uuid4())
    pid, uid = uuid.uuid4(), uuid.uuid4()
    replacement_ws = AsyncMock()
    replacement = ModConnection(websocket=replacement_ws, participant_id=pid, user_id=uid)

    class _SwapThenFail(_FakeWS):
        async def send_text(self, message: str) -> None:
            room.mods[pid] = replacement
            raise RuntimeError("connection dropped")

    room.mods[pid] = ModConnection(websocket=_SwapThenFail(), participant_id=pid, user_id=uid)  # type: ignore[arg-type]

    await room.broadcast_to_mods("payload")
    await _drain()

    assert room.mods[pid] is replacement
    replacement_ws.close.assert_not_awaited()


@pytest.mark.asyncio
async def test_stalled_close_does_not_hold_the_broadcast():
    room = ConnectionManager().get_or_create_room(uuid.uuid4())
    stalled = _FakeWS(fail=True, hang_on_close=True)
    conn = SpectatorConnection(websocket=stalled)  # type: ignore[arg-type]
    room.spectators = {conn.connection_id: conn}

    await asyncio.wait_for(room.broadcast_to_spectators("payload"), timeout=1)
    await _drain()

    assert stalled.close_codes  # close was started, in the background
    for task in list(handler_module._eviction_closes):
        task.cancel()  # the stalled handshake would otherwise outlive the test
    await _drain()


@pytest.mark.asyncio
async def test_failed_race_state_recipient_is_evicted_and_closed(monkeypatch):
    mgr = ConnectionManager()
    monkeypatch.setattr(race_spectator, "manager", mgr)

    async def no_invites(race_id):
        return []

    def failing_build(*args, **kwargs):
        raise RuntimeError("race_state failed")

    monkeypatch.setattr(race_spectator, "load_pending_invites", no_invites)
    monkeypatch.setattr(race_spectator, "build_race_state_payload", failing_build)
    race_id = uuid.uuid4()
    room = mgr.get_or_create_room(race_id)
    broken = _FakeWS()
    conn = SpectatorConnection(websocket=broken)  # type: ignore[arg-type]
    room.spectators = {conn.connection_id: conn}

    await race_spectator.broadcast_race_state_update(race_id, SimpleNamespace())  # type: ignore[arg-type]
    await _drain()

    assert room.spectators == {}
    _assert_closed_for_reconnect(broken)


@pytest.mark.asyncio
async def test_race_state_invite_load_failure_closes_spectators(monkeypatch):
    """Without the invites there is no state to send: spectators are closed so
    their reconnect resyncs, rather than kept on a stale state."""
    mgr = ConnectionManager()
    monkeypatch.setattr(race_spectator, "manager", mgr)

    async def failing_invites(race_id):
        raise RuntimeError("database unavailable")

    monkeypatch.setattr(race_spectator, "load_pending_invites", failing_invites)
    race_id = uuid.uuid4()
    room = mgr.get_or_create_room(race_id)
    ws = _FakeWS()
    conn = SpectatorConnection(websocket=ws)  # type: ignore[arg-type]
    room.spectators = {conn.connection_id: conn}

    await race_spectator.broadcast_race_state_update(race_id, SimpleNamespace())  # type: ignore[arg-type]
    await _drain()

    assert room.spectators == {}
    assert ws.sent == []
    _assert_closed_for_reconnect(ws)


@pytest.mark.asyncio
async def test_failed_training_spectator_is_evicted_and_closed():
    room = TrainingRoom(session_id=uuid.uuid4())
    broken = _FakeWS(fail=True)
    conn = TrainingSpectatorConnection(websocket=broken, user_id=uuid.uuid4())  # type: ignore[arg-type]
    room.spectators = {conn.connection_id: conn}

    await room.broadcast_to_spectators("payload")
    await _drain()

    assert room.spectators == {}
    _assert_closed_for_reconnect(broken)


@pytest.mark.asyncio
async def test_failed_training_mod_is_evicted_and_closed():
    room = TrainingRoom(session_id=uuid.uuid4())
    broken = _FakeWS(fail=True)
    room.mod = TrainingModConnection(websocket=broken, user_id=uuid.uuid4())  # type: ignore[arg-type]

    await room.broadcast_to_mod("payload")
    await _drain()

    assert room.mod is None
    _assert_closed_for_reconnect(broken)


@pytest.mark.asyncio
async def test_replaced_training_mod_is_not_closed_by_ghost_eviction():
    """The ghost's failed send must not close the reconnect that replaced it."""
    room = TrainingRoom(session_id=uuid.uuid4())
    replacement_ws = AsyncMock()
    replacement = TrainingModConnection(websocket=replacement_ws, user_id=uuid.uuid4())

    class _SwapThenFail(_FakeWS):
        async def send_text(self, message: str) -> None:
            room.mod = replacement
            raise RuntimeError("connection dropped")

    room.mod = TrainingModConnection(websocket=_SwapThenFail(), user_id=replacement.user_id)  # type: ignore[arg-type]

    await room.broadcast_to_mod("payload")
    await _drain()

    assert room.mod is replacement
    replacement_ws.close.assert_not_awaited()
