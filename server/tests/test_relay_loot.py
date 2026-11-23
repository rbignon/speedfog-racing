"""Relay boss loot: what a counted kill sends the team, and the catch-up after a connection."""

import logging
from typing import Any

import pytest

from speedfog_racing.services.relay import loot_entry, team_loot

from . import test_integration as _integration
from .relay_fixtures import (
    BOSS_FLAG,
    BOSS_NAME,
    BOSS_NODE,
    FOG_FLAG,
    RELAY_BLOCK,
    START_NODE,
    RelayModClient,
    barrier,
    load_team,
    member_view,
    pass_gate,
    progress_graph,
    relay_graph,
    setup_relay_race,
    start_relay,
    started_mods,
)

integration_db = _integration.integration_db
integration_client = _integration.integration_client

ENTRY = {
    "flag": BOSS_FLAG,
    "received_flag": 1050297000,
    "pickup_flags": [510060],
    "items": [{"id": 536874924, "qty": 1}],
    "rune_speffect": 755891000,
    "runes": 13000,
}


@pytest.fixture
def relay_race(integration_db, integration_client):
    return setup_relay_race(integration_db)


@pytest.fixture
def mods(integration_client, relay_race):
    yield from started_mods(integration_client, relay_race)


@pytest.fixture
def trio_race(integration_db, integration_client):
    return setup_relay_race(integration_db, team_size=3)


@pytest.fixture
def trio_mods(integration_client, trio_race):
    yield from started_mods(integration_client, trio_race)


def _pid(relay_race: dict[str, Any], team: int, member: int) -> str:
    pid: str = relay_race["teams"][team]["members"][member]["participant_id"]
    return pid


def _kill(mod: RelayModClient) -> None:
    """The holder takes the gate into BOSS_NODE and kills its boss."""
    pass_gate(mod, FOG_FLAG, 20_000, 1)
    mod.send_event_flag(BOSS_FLAG, igt_ms=40_000, message_id=2)
    mod.receive_until("event_flag_ack", lambda m: m["message_id"] == 2)


def _counted(mod: RelayModClient, killer_id: str) -> list[str]:
    """Wait for the ``relay_update`` that follows the kill (the killer's zones
    at 2: the start's exit, then the kill); the kill's loot goes out before it.
    Returns the types of the messages received before it."""
    mod.receive_until("relay_update", lambda m: member_view(m, killer_id)["zones"] == 2)
    return [m["type"] for m in mod.skipped]


def _seen_until_barrier(mod: RelayModClient) -> list[str]:
    """The types of every message the mod received until the server handled
    what it sent so far."""
    barrier(mod)
    return [m["type"] for m in mod.skipped]


def _connect(
    client: Any, relay_race: dict[str, Any], mods: dict[str, RelayModClient], pid: str
) -> RelayModClient:
    """The member's mod connects again (its previous socket closed), past its ``auth_ok``."""
    token = next(
        m["mod_token"]
        for team in relay_race["teams"]
        for m in team["members"]
        if m["participant_id"] == pid
    )
    back = mods[pid] = RelayModClient.connect(client, relay_race["race_id"], token, pid)
    assert back.auth(protocol_version="1.19")["type"] == "auth_ok"
    return back


def _drop(mods: dict[str, RelayModClient], pid: str) -> None:
    mods[pid].disconnect()
    mods[pid].close()


# --- Reading the seed ---


def test_loot_entry_reads_the_graph():
    entry = loot_entry({"relay": RELAY_BLOCK}, BOSS_FLAG)
    assert entry is not None and entry.model_dump() == ENTRY


def test_an_item_id_past_the_i32_range_is_kept():
    # An ash of war carries its category in the top bit of the id.
    raw = {**RELAY_BLOCK["loot"]["10000800"], "items": [{"id": 2147503848, "qty": 1}]}
    entry = loot_entry({"relay": {**RELAY_BLOCK, "loot": {"10000800": raw}}}, BOSS_FLAG)
    assert entry is not None and entry.items[0].id == 2147503848


@pytest.mark.parametrize(
    "bad",
    [
        {"runes": 1},  # keys missing
        {**RELAY_BLOCK["loot"]["10000800"], "items": [{"id": -1, "qty": 1}]},
        {**RELAY_BLOCK["loot"]["10000800"], "items": [{"id": 1, "qty": 0}]},
        {**RELAY_BLOCK["loot"]["10000800"], "received_flag": "x"},
        "not an entry",
    ],
)
def test_a_malformed_loot_entry_is_no_entry(bad, caplog):
    graph = {"relay": {**RELAY_BLOCK, "loot": {"10000800": bad}}}
    with caplog.at_level(logging.WARNING):
        assert loot_entry(graph, BOSS_FLAG) is None
    assert [r.getMessage() for r in caplog.records] == [
        f"Relay loot entry unusable: flag={BOSS_FLAG}"
    ]


def test_team_loot_follows_the_teams_dead_bosses():
    history = [
        {"node_id": START_NODE, "igt_ms": 0, "type": "spawn"},
        {"node_id": BOSS_NODE, "igt_ms": 9, "type": "fog", "boss_kill_igt_ms": 20},
    ]
    graph = relay_graph(progress_graph())
    assert [e.flag for e in team_loot(graph, history)] == [BOSS_FLAG]
    assert team_loot(graph, history[:1]) == []


# --- A kill ---


def test_a_kill_sends_the_loot_to_the_teammate_and_marks_the_killer_paid(
    integration_client, relay_race, mods
):
    killer, mate = mods[_pid(relay_race, 0, 0)], mods[_pid(relay_race, 0, 1)]
    _kill(killer)
    to_mate = mate.receive_until("relay_loot")
    assert to_mate["entries"] == [ENTRY] and to_mate["paid"] is False
    assert to_mate["announce"] == {
        "runner": relay_race["teams"][0]["members"][0]["user"].twitch_display_name,
        "boss": BOSS_NAME,
    }
    to_killer = killer.receive_until("relay_loot")
    assert to_killer["entries"] == [ENTRY] and to_killer["paid"] is True
    assert to_killer["announce"] is None


def test_the_other_team_and_a_member_out_get_no_loot(integration_client, trio_race, trio_mods):
    killer_id, mate_id, out_id = (_pid(trio_race, 0, i) for i in range(3))
    out_user = trio_race["teams"][0]["members"][2]["user"]
    response = integration_client.post(
        f"/api/races/{trio_race['race_id']}/abandon",
        headers={"Authorization": f"Bearer {out_user.api_token}"},
    )
    assert response.status_code == 200, response.json()
    trio_mods[killer_id].receive_until(
        "relay_update", lambda m: member_view(m, out_id)["status"] == "abandoned"
    )

    _kill(trio_mods[killer_id])
    assert trio_mods[mate_id].receive_until("relay_loot")["entries"] == [ENTRY]
    _counted(trio_mods[killer_id], killer_id)

    # The member out reads the kill in its team's update, the other team in
    # the team's row: no loot before or with it.
    news = {out_id: "relay_update", **{_pid(trio_race, 1, i): "player_update" for i in range(3)}}
    for pid, kill_news in news.items():
        seen = _seen_until_barrier(trio_mods[pid])
        assert kill_news in seen and "relay_loot" not in seen, pid

    # Nor after a connection of its own.
    _drop(trio_mods, out_id)
    back = _connect(integration_client, trio_race, trio_mods, out_id)
    seen = _seen_until_barrier(back)
    assert "relay_update" in seen and "relay_loot" not in seen


# --- A connection ---


def test_a_reconnecting_member_gets_every_loot_of_the_team_after_its_update(
    integration_client, relay_race, mods
):
    killer_id, mate_id = _pid(relay_race, 0, 0), _pid(relay_race, 0, 1)
    _drop(mods, mate_id)
    _kill(mods[killer_id])
    _counted(mods[killer_id], killer_id)

    back = _connect(integration_client, relay_race, mods, mate_id)
    loot = back.receive_until("relay_loot")
    assert "relay_update" in [m["type"] for m in back.skipped]
    assert loot == {"type": "relay_loot", "entries": [ENTRY], "paid": False, "announce": None}
    assert "relay_loot" not in _seen_until_barrier(back)  # one message


def test_a_member_connecting_before_any_kill_gets_no_loot_message(
    integration_client, relay_race, mods
):
    mate_id = _pid(relay_race, 0, 1)
    # The team stands in the boss's zone, the boss alive.
    pass_gate(mods[_pid(relay_race, 0, 0)], FOG_FLAG, 20_000, 1)
    _drop(mods, mate_id)

    back = _connect(integration_client, relay_race, mods, mate_id)
    seen = _seen_until_barrier(back)
    assert "relay_update" in seen and "relay_loot" not in seen


def test_a_kill_without_a_loot_entry_is_counted_and_sends_no_loot(
    integration_client, integration_db, caplog
):
    graph = progress_graph()
    graph["relay"]["loot"] = {}
    relay_race = setup_relay_race(integration_db, graph=graph)
    mods = start_relay(integration_client, relay_race)
    try:
        killer_id = _pid(relay_race, 0, 0)
        with caplog.at_level(logging.WARNING):
            _kill(mods[killer_id])
            before = _counted(mods[killer_id], killer_id)
        history = load_team(relay_race).zone_history or []
        assert [e.get("boss_kill_igt_ms") for e in history] == [None, 40_000]
        assert "relay_loot" not in before
        for mod in mods.values():
            assert "relay_loot" not in _seen_until_barrier(mod)
        warnings = [
            r.getMessage()
            for r in caplog.records
            if r.levelno == logging.WARNING and "loot" in r.getMessage()
        ]
        assert warnings == [f"Relay loot entry missing: flag={BOSS_FLAG}"]
    finally:
        for mod in mods.values():
            mod.close()
