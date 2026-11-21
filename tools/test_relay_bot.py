"""Tests for relay_bot.py's decisions (no database, no server, no socket).

Run from tools/: cd tools && uv run --project ../server pytest test_relay_bot.py
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from relay_bot import (
    FAKE_STATE,
    FRESH_IGT_MS,
    Bot,
    finish_warning,
    load_state,
    next_action,
    next_gate,
    parse_team,
    request_pass,
    request_take,
    stats_plausible,
    tick,
)

ME = "p-me"
MATE = "p-mate"
FLAGS = {
    "lock_flag": 1050290500,
    "chapel_warp_flag": 1050290501,
    "warp_flag_base": 1050290510,
    "zone_flag_base": 1050294000,
}


def member(pid: str, name: str, **over: Any) -> dict[str, Any]:
    return {
        "participant_id": pid,
        "name": name,
        "zones": 0,
        "status": "playing",
        "online": True,
        "ready": False,
        "validated": False,
        **over,
    }


def info(role: str = "waiting", **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "team_id": "t1",
        "team_name": "Alpha",
        "team_status": "playing",
        "cap": 4,
        "holder_id": ME if role == "holder" else MATE,
        "holder_online": True,
        "zone_name": None,
        "baton_free_in_s": None,
        "role": role,
        "gates_locked": False,
        "members": [member(ME, "me"), member(MATE, "mate")],
        "flags": FLAGS,
    }
    return {**base, **over}


class Clock:
    def __init__(self) -> None:
        self.t = 100.0

    def __call__(self) -> float:
        return self.t


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def bot(clock: Clock) -> Bot:
    return Bot(
        name="me", participant_id=ME, mod_token="tok", team_name="Alpha", clock=clock
    )


def running(bot: Bot, relay: dict[str, Any], igt_ms: int = 0) -> None:
    """Put the bot where an auth_ok on a running race leaves it."""
    out = next_action(
        bot,
        {
            "type": "auth_ok",
            "race": {"status": "running"},
            "participants": [{"id": relay["team_id"], "igt_ms": igt_ms}],
            "relay": relay,
        },
    )
    del out


TAKE: dict[str, Any] = {
    "type": "relay_take",
    "handoff_id": "h2",
    "state": None,
    "igt_ms": 90_000,
    "defeat_flags": [],
    "warp_flag": None,
    "zone_name": None,
}

GRAPH = {
    "nodes": {
        "start": {"type": "start", "layer": 0, "exits": [{"to": "a"}]},
        "a": {"type": "mini_dungeon", "layer": 1, "exits": [{"to": "b"}]},
        "b": {"type": "mini_dungeon", "layer": 2, "exits": [{"to": "final"}]},
        "final": {"type": "final_boss", "layer": 3, "exits": []},
    },
    "event_map": {"21": "a", "22": "b", "23": "final"},
}


def test_bot_answers_a_release_with_its_state(bot: Bot) -> None:
    running(bot, info("holder"), igt_ms=40_000)
    out = next_action(
        bot, {"type": "relay_release", "handoff_id": "h1", "to_name": "x"}
    )
    assert out is not None
    assert (out["type"], out["handoff_id"], len(out["state"]["attributes"])) == (
        "relay_state",
        "h1",
        8,
    )
    # The IGT it answers with is the team's, not its own save's.
    assert out["igt_ms"] == 40_000


def test_release_igt_follows_the_clock(bot: Bot, clock: Clock) -> None:
    running(bot, info("holder"), igt_ms=40_000)
    clock.t += 5
    out = next_action(
        bot, {"type": "relay_release", "handoff_id": "h1", "to_name": "x"}
    )
    assert out is not None and out["igt_ms"] == 45_000


def test_bot_acknowledges_a_take_and_becomes_holder(bot: Bot) -> None:
    running(bot, info("waiting"))
    out = next_action(bot, TAKE)
    assert out == {"type": "relay_taken", "handoff_id": "h2"}
    assert bot.holder is True and bot.igt_ms == 90_000


def test_first_report_after_a_take_is_the_given_team_igt(
    bot: Bot, clock: Clock
) -> None:
    running(
        bot,
        info(
            "waiting", members=[member(ME, "me", validated=True), member(MATE, "mate")]
        ),
    )
    next_action(bot, TAKE)
    clock.t += 3
    (first,) = [m for m in tick(bot) if m["type"] == "status_update"]
    assert first["igt_ms"] == 90_000
    clock.t += 1
    (second,) = [m for m in tick(bot) if m["type"] == "status_update"]
    assert (
        second["igt_ms"] == 91_000
    )  # runs on from the first report, not from the take


def test_muted_bot_does_not_acknowledge(bot: Bot) -> None:
    running(bot, info("waiting"))
    bot.muted = True
    assert next_action(bot, TAKE) is None
    assert bot.holder is False
    # A bot that never took the baton reports nothing, whatever the server says.
    next_action(bot, {"type": "relay_update", "relay": info("holder")})
    assert [m for m in tick(bot) if m["type"] == "status_update"] == []


def test_relay_update_sets_the_role(bot: Bot) -> None:
    running(bot, info("holder"))
    assert bot.holder is True
    next_action(bot, {"type": "relay_update", "relay": info("waiting")})
    assert bot.holder is False


def test_waiting_runner_sends_a_fresh_first_report(bot: Bot) -> None:
    running(bot, info("waiting"), igt_ms=500_000)
    (msg,) = [m for m in tick(bot) if m["type"] == "status_update"]
    # The gate looks at the runner's own save, never the team's.
    assert msg["igt_ms"] <= FRESH_IGT_MS


def test_relay_ready_goes_out_once_validated_and_again_after_auth_ok(bot: Bot) -> None:
    running(bot, info("waiting"))
    assert [m for m in tick(bot) if m["type"] == "relay_ready"] == []
    validated = info(
        "waiting", members=[member(ME, "me", validated=True), member(MATE, "mate")]
    )
    next_action(bot, {"type": "relay_update", "relay": validated})
    assert [m for m in tick(bot) if m["type"] == "relay_ready"] == [
        {"type": "relay_ready", "ready": True}
    ]
    assert [m for m in tick(bot) if m["type"] == "relay_ready"] == []
    # Readiness does not survive the socket.
    out = next_action(
        bot,
        {
            "type": "auth_ok",
            "race": {"status": "running"},
            "participants": [],
            "relay": validated,
        },
    )
    assert out == {"type": "relay_ready", "ready": True}


def test_holder_is_not_ready_and_does_not_send_a_fresh_report_twice(bot: Bot) -> None:
    running(
        bot,
        info(
            "holder", members=[member(ME, "me", validated=True), member(MATE, "mate")]
        ),
    )
    sent = tick(bot)
    assert [m["type"] for m in sent] == ["status_update"]


def test_a_member_out_stops(bot: Bot) -> None:
    running(bot, info("holder"))
    gone = info(
        "waiting",
        members=[member(ME, "me", status="disqualified"), member(MATE, "mate")],
    )
    next_action(bot, {"type": "relay_update", "relay": gone})
    assert bot.out is True
    assert tick(bot) == []
    assert (
        next_action(bot, {"type": "relay_release", "handoff_id": "h", "to_name": "x"})
        is None
    )


def test_a_finished_team_stops(bot: Bot) -> None:
    running(bot, info("holder"))
    next_action(
        bot, {"type": "relay_update", "relay": info("waiting", team_status="finished")}
    )
    assert bot.out is True and tick(bot) == []


def test_pass_needs_the_baton_and_a_named_teammate(bot: Bot) -> None:
    running(bot, info("waiting"))
    assert isinstance(request_pass(bot, "mate"), str)  # not the holder
    running(bot, info("holder"))
    assert request_pass(bot, "mate") == {
        "type": "relay_handoff_request",
        "to_participant_id": MATE,
    }
    assert isinstance(request_pass(bot, "nobody"), str)
    assert isinstance(request_pass(bot, "me"), str)


def test_take_waits_for_the_baton_to_be_free(bot: Bot) -> None:
    running(bot, info("waiting", baton_free_in_s=42))
    refusal = request_take(bot)
    assert isinstance(refusal, str) and "42" in refusal
    next_action(
        bot, {"type": "relay_update", "relay": info("waiting", baton_free_in_s=0)}
    )
    assert request_take(bot) == {"type": "relay_take_request"}


def test_next_gate_steps_one_layer_then_the_final_boss() -> None:
    assert next_gate(GRAPH, "start") == ("a", 21)
    assert next_gate(GRAPH, "a") == ("b", 22)
    # At the deepest layer only the final boss is left.
    assert next_gate(GRAPH, "b") == ("final", 23)
    assert isinstance(next_gate(GRAPH, "final"), str)


def test_parse_team_rejects_what_a_run_cannot_use() -> None:
    assert parse_team("Alpha=a,b") == ("Alpha", ["a", "b"])
    for bad in ("Alpha", "=a,b", "Alpha=a", "Alpha=a,a", "Alpha=a,"):
        with pytest.raises(ValueError):
            parse_team(bad)


def test_finish_warns_unless_the_team_is_at_the_final_boss() -> None:
    assert finish_warning(GRAPH, "a") is not None
    assert finish_warning(GRAPH, "final") is None


# A level 30 character: attributes summing to 109.
STATE: dict[str, Any] = {
    "attributes": [20, 12, 15, 18, 16, 9, 9, 10],
    "level": 30,
    "runes": 12_345,
    "items": [2_000_005, 0x1000_0000 | 40_000, 0x4000_0000 | 4_000],
    "grace_flags": [71_190, 76_101],
}


def test_the_default_state_is_one_the_receivers_mod_writes() -> None:
    from speedfog_racing.websocket.schemas import CharacterState

    CharacterState.model_validate(FAKE_STATE)
    assert stats_plausible(FAKE_STATE)


def test_stats_plausible_is_the_mods_stat_rule() -> None:
    assert stats_plausible(STATE)
    # The level is the attribute sum minus 79: Vagabond's attributes at level
    # 1 are no character's.
    assert not stats_plausible({**FAKE_STATE, "level": 1})
    assert not stats_plausible({**STATE, "attributes": [0] * 8, "level": 0})
    assert not stats_plausible({**STATE, "attributes": [100] + [10] * 7, "level": 91})
    assert not stats_plausible({**STATE, "runes": 1_000_000_000})
    assert stats_plausible({**STATE, "runes": 999_999_999})


def test_bot_answers_a_release_with_the_state_it_was_given(bot: Bot) -> None:
    bot.state = STATE
    running(bot, info("holder"))
    out = next_action(
        bot, {"type": "relay_release", "handoff_id": "h1", "to_name": "x"}
    )
    assert out is not None and out["state"] == STATE


def test_load_state_reads_a_valid_file(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    path.write_text(json.dumps(STATE), encoding="utf-8")
    assert load_state(path) == STATE
    # The lists may be left out: the server's model gives them empty.
    bare = {k: STATE[k] for k in ("attributes", "level", "runes")}
    path.write_text(json.dumps(bare), encoding="utf-8")
    assert load_state(path) == {**bare, "items": [], "grace_flags": []}


def test_load_state_names_a_missing_file(tmp_path: Path) -> None:
    missing = tmp_path / "nope.json"
    with pytest.raises(ValueError, match="cannot read") as caught:
        load_state(missing)
    assert str(missing) in str(caught.value)


def test_load_state_refuses_what_the_server_would_drop(tmp_path: Path) -> None:
    path = tmp_path / "state.json"
    for bad in (
        "not json",
        json.dumps({**STATE, "attributes": [10, 10, 10]}),
        json.dumps({**STATE, "runes": -1}),
        json.dumps({**STATE, "items": list(range(4001))}),
        json.dumps({k: STATE[k] for k in ("attributes", "level")}),
    ):
        path.write_text(bad, encoding="utf-8")
        with pytest.raises(ValueError, match="not a valid CharacterState"):
            load_state(path)
