"""Relay baton: handoff, takeover, checkpoints and the two timeouts."""

import asyncio
import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import UUID, uuid4

import pytest
from sqlalchemy.dialects import postgresql

import speedfog_racing.websocket.race.relay as relay_ws
from speedfog_racing.models import ParticipantStatus, RaceStatus
from speedfog_racing.services.relay import relay_cap, team_defeat_flags
from speedfog_racing.websocket.race.manager import (
    ConnectionManager,
    ModConnection,
    RaceRoom,
    manager,
)
from speedfog_racing.websocket.race.relay_mod import RelayModHandler

from . import test_integration as _integration
from .relay_fixtures import (
    BOSS_FLAG,
    BOSS_NODE,
    FINAL_NODE,
    FOG_FLAG,
    PLAIN_NODE,
    PROGRESS_TOTAL_LAYERS,
    RELAY_BLOCK,
    SECOND_FOG_FLAG,
    START_GRACE,
    START_NODE,
    THIRD_FOG_FLAG,
    RelayModClient,
    barrier,
    connect_spectator,
    load_team,
    patch_member,
    patch_race,
    patch_team,
    progress_graph,
    setup_relay_race,
    start_relay,
)

integration_db = _integration.integration_db
integration_client = _integration.integration_client

STATE = {
    "attributes": [40, 20, 25, 30, 14, 9, 9, 7],
    "level": 68,
    "runes": 15230,
    "items": [2000005, 2147493648],
    "grace_flags": [71000, 76101],
}
OTHER_STATE = {**STATE, "level": 70, "runes": 0}
CAP = relay_cap(PROGRESS_TOTAL_LAYERS, 2)
# The warp flag of the first gate's connection.
WARP = RELAY_BLOCK["warp_flag_base"] + (FOG_FLAG - RELAY_BLOCK["zone_flag_base"])
EVENT_MAP = progress_graph()["event_map"]


def _live_take_timers() -> list[Any]:
    return [
        pending
        for room in manager.rooms.values()
        for pending in room.relay_pending.values()
        if pending.timer is not None and not pending.timer.done()
    ]


def _wait_for_timers(seconds: float = 2.0) -> None:
    """Wait until no take timer is running (each fired or was stopped)."""
    deadline = time.monotonic() + seconds
    while _live_take_timers() and time.monotonic() < deadline:
        time.sleep(0.01)


def _started(client, relay_race):
    mods = start_relay(client, relay_race)
    yield mods
    # A relay_take timer runs in the server's loop: a test that starts one
    # acknowledges the take or waits for the timer to fire.
    left = _live_take_timers()
    for mod in mods.values():
        mod.close()
    assert not left, "a relay_take timer outlived its test"


@pytest.fixture
def relay_race(integration_db, integration_client):
    return setup_relay_race(integration_db)


@pytest.fixture
def mods(integration_client, relay_race):
    yield from _started(integration_client, relay_race)


@pytest.fixture
def trio_race(integration_db, integration_client):
    return setup_relay_race(integration_db, team_size=3)


@pytest.fixture
def trio_mods(integration_client, trio_race):
    yield from _started(integration_client, trio_race)


def _pid(relay_race, team: int, member: int) -> str:
    return relay_race["teams"][team]["members"][member]["participant_id"]


def _me(update: dict[str, Any], participant_id: str) -> dict[str, Any]:
    return next(m for m in update["relay"]["members"] if m["participant_id"] == participant_id)


def _validate(mod: RelayModClient) -> None:
    """The member's first report under 60 s passes its fresh-save gate."""
    mod.send_status_update(igt_ms=2_000, death_count=0)
    mod.receive_until("relay_update", lambda m: _me(m, mod.participant_id)["validated"])


def _set_ready(mod: RelayModClient) -> None:
    """The member is loaded at the Chapel with its lock raised."""
    mod.send({"type": "relay_ready", "ready": True})
    mod.receive_until("relay_update", lambda m: _me(m, mod.participant_id)["ready"])


def _make_receiver(mod: RelayModClient) -> None:
    _validate(mod)
    _set_ready(mod)


def _gate(mod: RelayModClient, flag: int, igt_ms: int, message_id: int) -> None:
    mod.send_event_flag(flag, igt_ms=igt_ms, message_id=message_id)
    mod.receive_until("zone_update", lambda m: m["node_id"] == EVENT_MAP[str(flag)])


def _kill(mod: RelayModClient, igt_ms: int, message_id: int) -> None:
    mod.send_event_flag(BOSS_FLAG, igt_ms=igt_ms, message_id=message_id)
    mod.receive_until("event_flag_ack", lambda m: m["message_id"] == message_id)


def _release(holder: RelayModClient, target_id: str) -> dict[str, Any]:
    holder.send({"type": "relay_handoff_request", "to_participant_id": target_id})
    return holder.receive_until("relay_release")


def _hand_off(
    holder: RelayModClient, target: RelayModClient, *, igt_ms: int = 5_000
) -> dict[str, Any]:
    release = _release(holder, target.participant_id)
    holder.send(
        {
            "type": "relay_state",
            "handoff_id": release["handoff_id"],
            "state": STATE,
            "igt_ms": igt_ms,
        }
    )
    return target.receive_until("relay_take")


def _taken(mod: RelayModClient, take: dict[str, Any]) -> None:
    """Acknowledge a take; the barrier proves the server handled it."""
    mod.send({"type": "relay_taken", "handoff_id": take["handoff_id"]})
    barrier(mod)


def _holder_gone(update: dict[str, Any]) -> bool:
    """The team's holder went offline (a setup-time update has no holder)."""
    return update["relay"]["holder_id"] is not None and not update["relay"]["holder_online"]


def _refusal(mod: RelayModClient) -> str:
    code: str = mod.receive_until("relay_refused")["code"]
    return code


def _first_of(mod: RelayModClient, types: tuple[str, ...]) -> dict[str, Any]:
    for _ in range(50):
        msg = mod.receive()
        if msg["type"] in types:
            return msg
    raise TimeoutError(f"none of {types}")


# --- Handoff ---


def test_handoff_sequence(integration_client, relay_race, mods):
    holder_id, target_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    holder, target = mods[holder_id], mods[target_id]
    _gate(holder, FOG_FLAG, 20_000, 1)
    _kill(holder, 40_000, 2)
    _make_receiver(target)
    # The giver played on since its last report.
    patch_team(relay_race, last_igt_change_at=datetime.now(UTC) - timedelta(minutes=2))
    spectator = connect_spectator(integration_client, relay_race["race_id"])
    try:
        release = _release(holder, target_id)
        assert release["to_name"] == "Relay Runner 1"
        holder.send(
            {
                "type": "relay_state",
                "handoff_id": release["handoff_id"],
                "state": STATE,
                "igt_ms": 125_000,
            }
        )

        take = target.receive_until("relay_take")
        assert (take["state"], take["igt_ms"], take["handoff_id"]) == (
            STATE,
            125_000,
            release["handoff_id"],
        )
        # The receiver restarts the current zone, whose boss stays dead.
        assert (take["warp_flag"], take["zone_name"], take["defeat_flags"]) == (
            WARP,
            "Godrick the Grafted",
            [BOSS_FLAG],
        )
        team = load_team(relay_race)
        assert (team.holder_id, team.character_state, team.character_state_igt_ms) == (
            UUID(target_id),
            STATE,
            125_000,
        )
        assert team.igt_ms == 125_000
        # The giver locks on the server's word only.
        assert holder.receive_until("relay_update")["relay"]["role"] == "waiting"
        assert target.receive_until("relay_update")["relay"]["role"] == "holder"

        target.send({"type": "relay_taken", "handoff_id": take["handoff_id"]})
        team_id = relay_race["teams"][0]["id"]
        board = spectator.receive_until(
            "leaderboard_update",
            lambda m: any(
                p["id"] == team_id and p["relay_holder_id"] == target_id for p in m["participants"]
            ),
        )
        assert board
        barrier(target)
    finally:
        spectator.close()


def test_handoff_before_any_gate_has_no_warp(relay_race, mods):
    holder, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(target)

    take = _hand_off(holder, target)

    # No gate taken yet: the receiver is unlocked at the Chapel.
    assert (take["warp_flag"], take["zone_name"], take["defeat_flags"]) == (None, None, [])
    _taken(target, take)


@pytest.mark.parametrize(
    "case,code",
    [
        ("sender_is_waiting", "not_holder"),
        ("target_offline", "target_unavailable"),
        ("target_not_ready", "target_unavailable"),
        ("target_other_team", "target_unavailable"),
        ("target_abandoned", "target_unavailable"),
        ("target_is_the_holder", "target_unavailable"),
        ("target_not_validated", "not_validated"),
        ("target_at_cap", "target_at_cap"),
        ("handoff_pending", "busy"),
    ],
)
def test_handoff_refusals(relay_race, mods, case, code):
    holder_id, target_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    holder, target = mods[holder_id], mods[target_id]
    asker, to = holder, target_id
    if case == "sender_is_waiting":
        _make_receiver(target)
        asker, to = target, holder_id
    elif case == "target_offline":
        _make_receiver(target)
        target.disconnect()
        holder.receive_until("relay_update", lambda m: not _me(m, target_id)["online"])
    elif case == "target_not_ready":
        _validate(target)
    elif case == "target_other_team":
        to = _pid(relay_race, 1, 1)
        _make_receiver(mods[to])
    elif case == "target_abandoned":
        _make_receiver(target)
        patch_member(relay_race, target_id, status=ParticipantStatus.ABANDONED)
    elif case == "target_is_the_holder":
        to = holder_id
    elif case == "target_not_validated":
        _set_ready(target)
    elif case == "target_at_cap":
        _make_receiver(target)
        patch_member(relay_race, target_id, relay_zones=CAP)
    elif case == "handoff_pending":
        _make_receiver(target)
        _release(holder, target_id)

    asker.send({"type": "relay_handoff_request", "to_participant_id": to})

    assert _refusal(asker) == code
    assert load_team(relay_race).holder_id == UUID(holder_id)


def test_a_capped_runner_cannot_receive_even_on_the_final_zone(relay_race, mods):
    holder, target_id = mods[_pid(relay_race, 0, 0)], _pid(relay_race, 0, 1)
    for message_id, flag in enumerate((FOG_FLAG, SECOND_FOG_FLAG, THIRD_FOG_FLAG), start=1):
        _gate(holder, flag, 20_000 * message_id, message_id)
    _make_receiver(mods[target_id])
    patch_member(relay_race, target_id, relay_zones=CAP)

    holder.send({"type": "relay_handoff_request", "to_participant_id": target_id})

    assert _refusal(holder) == "target_at_cap"
    assert load_team(relay_race).current_zone == FINAL_NODE


@pytest.mark.parametrize("when", ["countdown", "race_finished", "team_finished"])
def test_requests_wait_for_a_running_team(relay_race, mods, when):
    holder, waiting = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(waiting)
    if when == "countdown":
        patch_race(relay_race, started_at=datetime.now(UTC) + timedelta(minutes=1))
    elif when == "race_finished":
        patch_race(relay_race, status=RaceStatus.FINISHED)
    else:
        patch_team(relay_race, status=ParticipantStatus.FINISHED)

    holder.send({"type": "relay_handoff_request", "to_participant_id": waiting.participant_id})
    assert _refusal(holder) == "busy"
    waiting.send({"type": "relay_take_request"})
    assert _refusal(waiting) == "busy"


def test_a_flip_to_a_target_gone_offline_frees_the_baton(relay_race, mods):
    giver, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    target_id = target.participant_id
    _make_receiver(target)
    release = _release(giver, target_id)
    target.disconnect()
    giver.receive_until("relay_update", lambda m: not _me(m, target_id)["online"])

    giver.send(
        {
            "type": "relay_state",
            "handoff_id": release["handoff_id"],
            "state": STATE,
            "igt_ms": 5_000,
        }
    )

    update = giver.receive_until("relay_update", lambda m: m["relay"]["holder_id"] == target_id)
    assert (update["relay"]["role"], update["relay"]["baton_free_in_s"]) == ("waiting", 0)
    team = load_team(relay_race)
    assert (team.holder_id, team.baton_free, team.character_state) == (UUID(target_id), True, STATE)
    assert not _live_take_timers()  # nobody is waited for


# --- Takeover ---


def test_takeover_waits_60_seconds_of_holder_absence(relay_race, mods):
    holder, waiting = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _gate(holder, FOG_FLAG, 20_000, 1)
    holder.send({"type": "relay_state", "handoff_id": None, "state": STATE, "igt_ms": 30_000})
    _kill(holder, 40_000, 2)  # after the checkpoint
    holder.send_status_update(igt_ms=50_000, death_count=0)
    holder.receive_until("player_update", lambda m: m["player"]["igt_ms"] == 50_000)
    _make_receiver(waiting)

    holder.disconnect()
    gone = waiting.receive_until("relay_update", _holder_gone)
    assert gone["relay"]["baton_free_in_s"] == 60
    waiting.send({"type": "relay_take_request"})
    assert _refusal(waiting) == "holder_online"

    patch_team(relay_race, holder_offline_since=datetime.now(UTC) - timedelta(seconds=60))
    waiting.send({"type": "relay_take_request"})

    take = waiting.receive_until("relay_take")
    # The last checkpoint, the last IGT received, and the boss killed after
    # the checkpoint still dead for the taker.
    assert (take["state"], take["igt_ms"], take["defeat_flags"]) == (STATE, 50_000, [BOSS_FLAG])
    assert (take["warp_flag"], take["zone_name"]) == (WARP, "Godrick the Grafted")
    team = load_team(relay_race)
    assert (team.holder_id, team.holder_offline_since) == (UUID(waiting.participant_id), None)
    _taken(waiting, take)


@pytest.mark.parametrize(
    "case,code",
    [
        ("holder_connected", "holder_online"),
        ("asker_abandoned", "target_unavailable"),
        ("asker_not_validated", "not_validated"),
        ("asker_not_ready", "not_ready"),
        ("asker_at_cap", "at_cap"),
    ],
)
def test_takeover_refusals(relay_race, mods, case, code):
    holder_id, waiting = _pid(relay_race, 0, 0), mods[_pid(relay_race, 0, 1)]
    if case == "asker_not_validated":
        _set_ready(waiting)
    elif case == "asker_not_ready":
        _validate(waiting)
    else:
        _make_receiver(waiting)
    if case == "asker_abandoned":
        patch_member(relay_race, waiting.participant_id, status=ParticipantStatus.ABANDONED)
    if case == "asker_at_cap":
        patch_member(relay_race, waiting.participant_id, relay_zones=CAP)
    if case != "holder_connected":
        patch_team(relay_race, baton_free=True)

    waiting.send({"type": "relay_take_request"})

    assert _refusal(waiting) == code
    assert load_team(relay_race).holder_id == UUID(holder_id)


def test_takeover_before_any_checkpoint_sends_no_state(relay_race, mods):
    waiting = mods[_pid(relay_race, 0, 1)]
    _make_receiver(waiting)
    patch_team(relay_race, baton_free=True)

    waiting.send({"type": "relay_take_request"})

    take = waiting.receive_until("relay_take")
    assert (take["state"], take["igt_ms"]) == (None, 1_000)
    _taken(waiting, take)


def test_two_requests_are_serialized(trio_race, trio_mods):
    first, second = trio_mods[_pid(trio_race, 0, 1)], trio_mods[_pid(trio_race, 0, 2)]
    _make_receiver(first)
    _make_receiver(second)
    patch_team(trio_race, baton_free=True)

    first.send({"type": "relay_take_request"})
    second.send({"type": "relay_take_request"})

    answers = {
        mod.participant_id: _first_of(mod, ("relay_take", "relay_refused"))
        for mod in (first, second)
    }
    assert sorted(m["type"] for m in answers.values()) == ["relay_refused", "relay_take"]
    assert next(m for m in answers.values() if m["type"] == "relay_refused")["code"] == "busy"
    taker = next(
        mod for mod in (first, second) if answers[mod.participant_id]["type"] == "relay_take"
    )
    assert load_team(trio_race).holder_id == UUID(taker.participant_id)
    _taken(taker, answers[taker.participant_id])


# --- The two timeouts ---


def test_unacknowledged_take_frees_the_baton_for_the_giver_too(monkeypatch, relay_race, mods):
    monkeypatch.setattr(relay_ws, "RELAY_TAKE_TIMEOUT_S", 0.05)
    giver, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(target)
    first = _hand_off(giver, target)  # the target never answers

    assert giver.receive_until("relay_update")["relay"]["role"] == "waiting"
    freed = giver.receive_until("relay_update", lambda m: m["relay"]["baton_free_in_s"] == 0)
    assert freed["relay"]["role"] == "waiting"
    assert load_team(relay_race).baton_free is True

    _set_ready(giver)  # back at the Chapel
    giver.send({"type": "relay_take_request"})
    take = giver.receive_until("relay_take")
    assert take["handoff_id"] != first["handoff_id"] and take["state"] == STATE
    _taken(giver, take)
    team = load_team(relay_race)
    assert (team.holder_id, team.baton_free) == (UUID(giver.participant_id), False)


def test_a_nominal_holder_takes_its_free_baton_back(monkeypatch, relay_race, mods):
    monkeypatch.setattr(relay_ws, "RELAY_TAKE_TIMEOUT_S", 0.05)
    giver, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(target)
    first_take = _hand_off(giver, target)  # its mod misses it, the timer fires

    freed = target.receive_until("relay_update", lambda m: m["relay"]["baton_free_in_s"] == 0)
    assert freed["relay"]["role"] == "waiting"  # still the nominal holder
    assert load_team(relay_race).holder_id == UUID(target.participant_id)

    target.send({"type": "relay_take_request"})
    take = target.receive_until("relay_take")
    assert take["handoff_id"] != first_take["handoff_id"]
    _taken(target, take)


def test_a_late_relay_taken_takes_the_free_baton_back(monkeypatch, relay_race, mods):
    monkeypatch.setattr(relay_ws, "RELAY_TAKE_TIMEOUT_S", 0.05)
    giver, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(target)
    take = _hand_off(giver, target)
    target.receive_until("relay_update", lambda m: m["relay"]["baton_free_in_s"] == 0)

    target.send({"type": "relay_taken", "handoff_id": take["handoff_id"]})

    back = target.receive_until("relay_update", lambda m: m["relay"]["role"] == "holder")
    assert back["relay"]["baton_free_in_s"] is None
    assert load_team(relay_race).baton_free is False
    barrier(target)


def test_release_not_answered_leaves_the_holder_in_place(monkeypatch, relay_race, mods):
    monkeypatch.setattr(relay_ws, "RELAY_RELEASE_TIMEOUT_S", 0.05)
    holder_id, target_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    holder = mods[holder_id]
    _make_receiver(mods[target_id])
    _release(holder, target_id)

    time.sleep(0.1)

    assert load_team(relay_race).holder_id == UUID(holder_id)
    assert _release(holder, target_id)["to_name"] == "Relay Runner 1"  # not "busy" any more


# --- State checkpoints ---


def test_late_or_foreign_relay_state_flips_nothing(monkeypatch, relay_race, mods):
    monkeypatch.setattr(relay_ws, "RELAY_RELEASE_TIMEOUT_S", 0.05)
    holder_id, waiting_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    holder, waiting = mods[holder_id], mods[waiting_id]
    _make_receiver(waiting)
    expired = _release(holder, waiting_id)["handoff_id"]
    time.sleep(0.1)

    holder.send({"type": "relay_state", "handoff_id": expired, "state": STATE, "igt_ms": 30_000})
    # A giver who already locked learns it still holds the baton.
    assert holder.receive_until("relay_update")["relay"]["role"] == "holder"
    team = load_team(relay_race)
    assert (team.holder_id, team.character_state) == (UUID(holder_id), STATE)

    holder.send({"type": "relay_state", "handoff_id": "unknown", "state": STATE, "igt_ms": 31_000})
    assert holder.receive_until("relay_update")["relay"]["role"] == "holder"

    waiting.send({"type": "relay_state", "handoff_id": None, "state": OTHER_STATE, "igt_ms": 1})
    assert waiting.receive_until("relay_update")["relay"]["role"] == "waiting"
    team = load_team(relay_race)
    assert (team.holder_id, team.character_state) == (UUID(holder_id), STATE)


@pytest.mark.parametrize(
    "payload",
    [
        {"state": {"attributes": [1, 2]}},
        {"state": {**STATE, "items": list(range(4001))}},
        {"state": "nope"},
        {"state": STATE, "igt_ms": -5},
        {"state": STATE, "igt_ms": "late"},
    ],
)
def test_malformed_relay_state_is_dropped(relay_race, mods, payload):
    holder = mods[_pid(relay_race, 0, 0)]

    holder.send({"type": "relay_state", "handoff_id": None, "igt_ms": 20_000, **payload})
    barrier(holder)  # the socket still works

    team = load_team(relay_race)
    assert (team.character_state, team.igt_ms) == (None, 1_000)
    holder.send({"type": "relay_state", "handoff_id": None, "state": STATE, "igt_ms": 21_000})
    barrier(holder)
    assert load_team(relay_race).character_state == STATE


def test_checkpoint_is_stored_with_the_team_igt(relay_race, mods):
    holder = mods[_pid(relay_race, 0, 0)]
    _gate(holder, FOG_FLAG, 40_000, 1)

    holder.send({"type": "relay_state", "handoff_id": None, "state": STATE, "igt_ms": 80_000})
    barrier(holder)

    team = load_team(relay_race)
    assert (team.character_state, team.character_state_igt_ms, team.igt_ms) == (
        STATE,
        80_000,
        80_000,
    )
    # A state whose IGT the wrong-save guard refuses may come from another
    # save: dropped, the previous checkpoint kept.
    holder.send(
        {"type": "relay_state", "handoff_id": None, "state": OTHER_STATE, "igt_ms": 900_000}
    )
    barrier(holder)
    team = load_team(relay_race)
    assert (team.character_state, team.character_state_igt_ms, team.igt_ms) == (
        STATE,
        80_000,
        80_000,
    )


def test_a_release_answered_on_an_implausible_igt_flips_nothing(relay_race, mods):
    holder_id, target_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    holder, target = mods[holder_id], mods[target_id]
    _make_receiver(target)
    release = _release(holder, target_id)

    holder.send(
        {
            "type": "relay_state",
            "handoff_id": release["handoff_id"],
            "state": STATE,
            "igt_ms": 900_000,
        }
    )

    # The giver still holds the baton, and is told so.
    assert holder.receive_until("relay_update")["relay"]["role"] == "holder"
    barrier(target)
    assert not [m for m in target.skipped if m["type"] == "relay_take"]
    team = load_team(relay_race)
    assert (team.holder_id, team.character_state, team.igt_ms) == (UUID(holder_id), None, 1_000)
    assert _release(holder, target_id)["to_name"] == "Relay Runner 1"  # the handoff was dropped


def test_the_receiver_is_not_listened_to_before_relay_taken(relay_race, mods):
    holder, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(target)
    take = _hand_off(holder, target)
    before = load_team(relay_race)

    # Its game still carries its own save's IGT and deaths, and its state.
    target.send({"type": "relay_state", "handoff_id": None, "state": OTHER_STATE, "igt_ms": 7_000})
    target.send_status_update(igt_ms=900_000, death_count=7)
    target.send_event_flag(FOG_FLAG, igt_ms=900_500, message_id=41)

    target.receive_until("event_flag_ack", lambda m: m["message_id"] == 41)
    assert not [m for m in target.skipped if m["type"] in ("error", "player_update")]
    team = load_team(relay_race)
    assert (team.igt_ms, team.death_count, team.current_zone, team.zone_history) == (
        before.igt_ms,
        before.death_count,
        before.current_zone,
        before.zone_history,
    )
    assert (team.entry_flag_id, team.character_state) == (None, STATE)

    _taken(target, take)
    target.send_status_update(igt_ms=6_000, death_count=0)
    target.receive_until("player_update", lambda m: m["player"]["igt_ms"] == 6_000)
    assert load_team(relay_race).igt_ms == 6_000


def test_a_first_runner_absent_at_the_start_waits_60_seconds(integration_client, relay_race):
    race_id = relay_race["race_id"]
    absent = relay_race["teams"][0]["members"][0]
    mods: dict[str, RelayModClient] = {}
    try:
        for team in relay_race["teams"]:
            for member in team["members"]:
                if member is absent:
                    continue
                pid = member["participant_id"]
                mods[pid] = RelayModClient.connect(
                    integration_client, race_id, member["mod_token"], pid
                )
                assert mods[pid].auth(protocol_version="1.19")["type"] == "auth_ok"
        response = integration_client.post(
            f"/api/races/{race_id}/start",
            headers={"Authorization": f"Bearer {relay_race['organizer'].api_token}"},
        )
        assert response.status_code == 200, response.json()
        patch_race(relay_race, started_at=datetime.now(UTC) - timedelta(seconds=1))
        waiting = mods[_pid(relay_race, 0, 1)]
        team = load_team(relay_race)
        assert team.holder_id == UUID(absent["participant_id"])
        assert team.holder_offline_since is not None  # absent from the start

        waiting.send_status_update(igt_ms=2_000, death_count=0)
        update = waiting.receive_until(
            "relay_update", lambda m: _me(m, waiting.participant_id)["validated"]
        )
        assert update["relay"]["baton_free_in_s"] == 60
        waiting.send({"type": "relay_take_request"})
        assert _refusal(waiting) == "holder_online"

        patch_team(relay_race, holder_offline_since=datetime.now(UTC) - timedelta(seconds=30))
        waiting.send({"type": "relay_ready", "ready": True})
        update = waiting.receive_until(
            "relay_update", lambda m: _me(m, waiting.participant_id)["ready"]
        )
        assert update["relay"]["baton_free_in_s"] in (29, 30)  # counting down

        patch_team(relay_race, holder_offline_since=datetime.now(UTC) - timedelta(seconds=60))
        waiting.send({"type": "relay_take_request"})
        _taken(waiting, waiting.receive_until("relay_take"))
    finally:
        for mod in mods.values():
            mod.close()


def test_a_take_between_the_holder_socket_pop_and_its_stamp_waits(relay_race):
    holder_id, asker_id = UUID(_pid(relay_race, 0, 0)), UUID(_pid(relay_race, 0, 1))
    patch_race(
        relay_race, status=RaceStatus.RUNNING, started_at=datetime.now(UTC) - timedelta(minutes=1)
    )
    patch_team(relay_race, status=ParticipantStatus.PLAYING, holder_id=holder_id)
    patch_member(relay_race, str(asker_id), status=ParticipantStatus.PLAYING, relay_validated=True)
    # The holder's socket left the room; its disconnect hook has not stamped yet.
    room = RaceRoom(race_id=UUID(relay_race["race_id"]))
    socket = AsyncMock()
    room.mods[asker_id] = ModConnection(websocket=socket, participant_id=asker_id, user_id=uuid4())
    room.relay_ready.add(asker_id)

    asyncio.run(
        relay_ws.request_take(relay_race["db"], room, asker_id, graph_json=progress_graph())
    )

    sent = [json.loads(call.args[0]) for call in socket.send_text.call_args_list]
    assert [(m["type"], m["code"]) for m in sent] == [("relay_refused", "holder_online")]
    team = load_team(relay_race)
    assert (team.holder_id, team.baton_free) == (holder_id, False)
    assert team.holder_offline_since is not None  # offline since now: the wait starts
    assert not room.relay_pending


def test_a_failure_after_the_flip_still_frees_the_baton(monkeypatch, relay_race, mods):
    monkeypatch.setattr(relay_ws, "RELAY_TAKE_TIMEOUT_S", 0.05)
    holder, waiting = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(waiting)
    patch_team(relay_race, baton_free=True)

    def broken(*args: Any, **kwargs: Any) -> list[int]:
        raise RuntimeError("after the flip's commit")

    monkeypatch.setattr(relay_ws, "team_defeat_flags", broken)
    waiting.send({"type": "relay_take_request"})

    # No relay_take went out, yet the take still expires.
    freed = waiting.receive_until(
        "relay_update",
        lambda m: (
            m["relay"]["holder_id"] == waiting.participant_id and m["relay"]["baton_free_in_s"] == 0
        ),
    )
    assert not [m for m in waiting.skipped if m["type"] == "relay_take"]
    assert freed["relay"]["role"] == "waiting"
    monkeypatch.setattr(relay_ws, "team_defeat_flags", team_defeat_flags)
    _set_ready(holder)
    holder.send({"type": "relay_take_request"})
    _taken(holder, holder.receive_until("relay_take"))


def test_a_take_timer_frees_nothing_once_the_team_is_out(monkeypatch, relay_race, mods):
    monkeypatch.setattr(relay_ws, "RELAY_TAKE_TIMEOUT_S", 0.5)
    giver, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(target)
    _hand_off(giver, target)

    patch_team(relay_race, status=ParticipantStatus.FINISHED)
    _wait_for_timers()

    assert load_team(relay_race).baton_free is False


def test_a_race_reset_stops_a_pending_take_timer(integration_client, relay_race, mods):
    giver, target = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _make_receiver(target)
    _hand_off(giver, target)
    [pending] = manager.rooms[UUID(relay_race["race_id"])].relay_pending.values()

    response = integration_client.post(
        f"/api/races/{relay_race['race_id']}/reset",
        headers={"Authorization": f"Bearer {relay_race['organizer'].api_token}"},
    )

    assert response.status_code == 200, response.json()
    _wait_for_timers()
    assert pending.timer is not None and pending.timer.cancelled()


# --- Connections and readiness ---


def test_a_waiting_runner_flag_or_query_takes_no_team_lock(monkeypatch, relay_race, mods):
    holder, waiting = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    locked: list[UUID | None] = []
    original = RelayModHandler._team_select

    def spy(self: RelayModHandler) -> Any:
        locked.append(self._participant_id)
        return original(self)

    monkeypatch.setattr(RelayModHandler, "_team_select", spy)
    waiting.send_event_flag(FOG_FLAG, igt_ms=3_000, message_id=51)
    waiting.receive_until("event_flag_ack", lambda m: m["message_id"] == 51)
    waiting.send_zone_query(START_GRACE, igt_ms=3_500, message_id=52)
    waiting.receive_until("zone_query_ack", lambda m: m["message_id"] == 52)
    barrier(holder)

    # Acknowledged on the lock-free read; only the holder's flag locks the team.
    assert UUID(waiting.participant_id) not in locked
    assert UUID(holder.participant_id) in locked


async def test_a_member_whose_socket_is_removed_loses_its_readiness():
    room = RaceRoom(race_id=uuid4())
    first, second = uuid4(), uuid4()
    for pid in (first, second):
        socket = AsyncMock()
        socket.send_text.side_effect = RuntimeError("gone")
        room.mods[pid] = ModConnection(websocket=socket, participant_id=pid, user_id=uuid4())
        room.relay_ready.add(pid)

    assert await room.send_to_mod(first, "{}") is False  # evicted on a failed send
    await room.broadcast_to_mods("{}")  # evicted on a failed broadcast
    assert (room.mods, room.relay_ready) == ({}, set())

    rooms = ConnectionManager()
    race_id, third = uuid4(), uuid4()
    await rooms.connect_mod(race_id, third, uuid4(), AsyncMock())
    rooms.rooms[race_id].relay_ready.add(third)
    await rooms.connect_mod(race_id, third, uuid4(), AsyncMock())  # replaced by a new socket
    assert rooms.rooms[race_id].relay_ready == set()
    await asyncio.sleep(0)  # the evicted sockets' background closes


def test_relay_ready_reports_a_member_waiting_at_the_chapel(relay_race, mods):
    holder, waiting = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]

    waiting.send({"type": "relay_ready", "ready": True})
    holder.receive_until("relay_update", lambda m: _me(m, waiting.participant_id)["ready"])
    waiting.send({"type": "relay_ready", "ready": False})

    assert _me(holder.receive_until("relay_update"), waiting.participant_id)["ready"] is False


def test_holder_disconnect_drops_its_release_and_a_reconnect_ends_the_wait(
    integration_client, relay_race, mods
):
    member = relay_race["teams"][0]["members"][0]
    holder_id, waiting = member["participant_id"], mods[_pid(relay_race, 0, 1)]
    _make_receiver(waiting)
    _release(mods[holder_id], waiting.participant_id)

    mods[holder_id].disconnect()
    gone = waiting.receive_until("relay_update", _holder_gone)
    assert gone["relay"]["baton_free_in_s"] == 60
    assert load_team(relay_race).holder_offline_since is not None
    mods[holder_id].close()

    holder = mods[holder_id] = RelayModClient.connect(
        integration_client, relay_race["race_id"], member["mod_token"], holder_id
    )
    assert holder.auth(protocol_version="1.19")["relay"]["role"] == "holder"
    back = waiting.receive_until("relay_update", lambda m: m["relay"]["holder_online"])
    assert back["relay"]["baton_free_in_s"] is None
    assert load_team(relay_race).holder_offline_since is None
    # The release died with the old socket.
    assert _release(holder, waiting.participant_id)["to_name"] == "Relay Runner 1"


# --- Rules and locks ---


def test_team_defeat_flags_name_each_killed_boss_once():
    graph = progress_graph()
    graph["nodes"][PLAIN_NODE]["defeat_flag"] = 10000700
    history = [
        {"node_id": START_NODE, "type": "spawn"},
        {"node_id": PLAIN_NODE, "boss_kill_igt_ms": 30_000},
        {"node_id": BOSS_NODE, "boss_kill_igt_ms": 50_000},
        {"node_id": BOSS_NODE, "type": "backtrack"},
        {"node_id": "gone_from_the_graph", "boss_kill_igt_ms": 60_000},
    ]

    assert team_defeat_flags(graph, history) == [10000700, BOSS_FLAG]
    assert team_defeat_flags(graph, None) == []


def test_flips_and_progress_writes_lock_the_team_row():
    """A flip and a progress write of one team are ordered by the database
    (SQLite ignores the lock, so the PostgreSQL statements are checked)."""
    handler = RelayModHandler(MagicMock(), uuid4(), MagicMock())
    handler._participant_id = uuid4()
    statements = [
        handler._team_select(),
        relay_ws.team_for_update(participant_id=uuid4()),
        relay_ws.team_for_update(team_id=uuid4()),
    ]

    for statement in statements:
        assert str(statement.compile(dialect=postgresql.dialect())).endswith(
            "FOR UPDATE OF relay_teams"
        )
