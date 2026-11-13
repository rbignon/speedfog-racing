"""Race items on the mod socket: the capability gate, the catalog, the wire shapes."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from speedfog_racing.config import settings
from speedfog_racing.models import Participant, Race, RaceItemEvent
from speedfog_racing.services.race_items import RACE_ITEMS_PLUGIN
from speedfog_racing.websocket.schemas import (
    RACE_ITEMS_OLD_MOD_MESSAGE,
    ItemBanner,
    ItemEffectMessage,
    ItemEffectPayload,
)

from . import test_integration as _integration
from .test_integration import BOSS_FLAG, ModTestClient, _patch_boss_graph, _start_race_and_connect

# The race fixtures of the integration suite, reused as they are.
integration_db = _integration.integration_db
integration_client = _integration.integration_client
race_with_participants = _integration.race_with_participants
seed_folder = _integration.seed_folder

HAMMER = {
    "name": "Hammer",
    "icon": "hammer",
    "goods_id": 1450807,
    "use_flag": 1050290107,
    "remove_flag": 1050290207,
    "effect_speffect": 4000001,
    "duration_ms": 20000,
}


def _patch_items_graph(
    integration_db, race_id: str, *, catalog: dict | None = None, items: bool = True
) -> None:
    """Make the race's seed carry the items plugin (the hammer alone by default)
    and set race_items on the race."""

    async def patch():
        async with integration_db() as db:
            result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(selectinload(Race.seed))
            )
            race = result.scalar_one()
            graph = json.loads(json.dumps(race.seed.graph_json))
            graph.setdefault("plugins", {})[RACE_ITEMS_PLUGIN] = {"enabled": True}
            graph[RACE_ITEMS_PLUGIN] = catalog if catalog is not None else {"hammer": HAMMER}
            race.seed.graph_json = graph
            race.race_items = items
            await db.commit()

    asyncio.run(patch())


def test_items_race_refuses_an_old_mod(integration_client, race_with_participants, integration_db):
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id)
    token = race_with_participants["players"][0]["mod_token"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        response = ModTestClient(ws, token).auth(protocol_version="1.11")
    assert response["type"] == "auth_error"
    assert response["message"] == RACE_ITEMS_OLD_MOD_MESSAGE


def test_items_race_accepts_1_12(integration_client, race_with_participants, integration_db):
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id)
    token = race_with_participants["players"][0]["mod_token"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        response = ModTestClient(ws, token).auth(protocol_version="1.12")
    assert response["type"] == "auth_ok"
    assert response["seed"]["race_item_catalog"]["hammer"] == {
        "goods_id": 1450807,
        "use_flag": 1050290107,
        "remove_flag": 1050290207,
        "name": "Hammer",
        "icon": "hammer",
    }
    assert response["race"]["race_items"] is True


def test_plain_race_sends_an_empty_catalog_and_accepts_old_mods(
    integration_client, race_with_participants
):
    race_id = race_with_participants["race_id"]
    token = race_with_participants["players"][0]["mod_token"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        response = ModTestClient(ws, token).auth(protocol_version="1.11")
    assert response["type"] == "auth_ok"
    assert response["seed"]["race_item_catalog"] == {}


def _expect_close(mod) -> int:
    """Drain the socket up to the server's close and return its code."""
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect) as exc_info:
        for _ in range(20):
            mod.receive(timeout=2)
    return exc_info.value.code


def test_switching_race_items_makes_the_mods_authenticate_again(
    integration_client, race_with_participants, integration_db
):
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    organizer = {"Authorization": f"Bearer {race_with_participants['organizer'].api_token}"}
    # The seed already carries the plugin: switching the option on draws no new seed.
    _patch_items_graph(integration_db, race_id, items=False)

    def switch(on: bool) -> None:
        response = integration_client.patch(
            f"/api/races/{race_id}", json={"race_items": on}, headers=organizer
        )
        assert response.status_code == 200, response.text

    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.12")["seed"]["race_item_catalog"] == {}
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.11")["type"] == "auth_ok"
        mod0.receive_until_type("leaderboard_update")  # mod1's connect broadcast

        # Unchanged: the connections stay.
        switch(False)
        mod0.send_ready()
        assert mod0.receive()["type"] == "leaderboard_update"

        switch(True)
        assert _expect_close(mod0) == 1000
        assert _expect_close(mod1) == 1000

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        response = mod0.auth(protocol_version="1.12")
        assert response["race"]["race_items"] is True
        assert response["seed"]["race_item_catalog"]["hammer"]["goods_id"] == HAMMER["goods_id"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        response = ModTestClient(ws1, players[1]["mod_token"]).auth(protocol_version="1.11")
        assert response["type"] == "auth_error"
        assert response["message"] == RACE_ITEMS_OLD_MOD_MESSAGE

    # Switching back off closes the mods too; they get an empty catalog again.
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        switch(False)
        assert _expect_close(mod0) == 1000
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        response = ModTestClient(ws0, players[0]["mod_token"]).auth(protocol_version="1.12")
        assert response["seed"]["race_item_catalog"] == {}


def test_item_effect_payload_dumps_without_nulls():
    message = ItemEffectMessage(
        item="red_shell",
        effect=ItemEffectPayload(kind="damage", base_pct=20, floor_pct=20, tail_pct=5),
        banner=ItemBanner(
            icon="red_shell", title="Red Shell", line="Hit for 20% HP", detail="from Gideohana"
        ),
    )
    dumped = json.loads(message.model_dump_json())
    assert dumped == {
        "type": "item_effect",
        "item": "red_shell",
        "effect": {"kind": "damage", "base_pct": 20, "floor_pct": 20, "tail_pct": 5},
        "banner": {
            "icon": "red_shell",
            "title": "Red Shell",
            "line": "Hit for 20% HP",
            "detail": "from Gideohana",
        },
        "reminder": None,
    }


# ---------------------------------------------------------------------------
# Grants: a new boss kill hands out an item
# ---------------------------------------------------------------------------

SECOND_BOSS_FLAG = 10000801
THIRD_BOSS_FLAG = 10000802


def _entry(name: str, goods_id: int) -> dict:
    return {
        "name": name,
        "icon": name.lower().replace(" ", "_"),
        "goods_id": goods_id,
        "use_flag": 1050290000 + goods_id % 100,
        "remove_flag": 1050290500 + goods_id % 100,
        "effect_speffect": None,
        "duration_ms": None,
    }


def _patch_grant_graph(integration_db, race_id: str, *, items: bool = True) -> None:
    """Three boss arenas (node_b, node_a, node_c; the last on layer 8 of 12) and a
    catalog with the hammer and the pouches."""
    _patch_boss_graph(integration_db, race_id)

    async def patch():
        async with integration_db() as db:
            result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(selectinload(Race.seed))
            )
            race = result.scalar_one()
            graph = json.loads(json.dumps(race.seed.graph_json))
            graph["nodes"]["node_a"].update(type="boss_arena", defeat_flag=SECOND_BOSS_FLAG)
            graph["nodes"]["node_c"].update(type="boss_arena", defeat_flag=THIRD_BOSS_FLAG, layer=8)
            graph["total_layers"] = 12
            graph.setdefault("plugins", {})[RACE_ITEMS_PLUGIN] = {"enabled": True}
            graph[RACE_ITEMS_PLUGIN] = {
                "hammer": HAMMER,
                "rune_pouch_1": _entry("Rune Pouch", 1450811),
                "rune_pouch_2": _entry("Rune Pouch", 1450812),
                "rune_pouch_3": _entry("Rune Pouch", 1450813),
            }
            race.seed.graph_json = graph
            race.race_items = items
            await db.commit()

    asyncio.run(patch())


def _start_items_race(integration_client, race_with_participants) -> str:
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {race_with_participants['organizer'].api_token}"},
    )
    assert response.status_code == 200
    return players[0]["mod_token"]


def _walk_three_arenas(mod0) -> None:
    """Visit node_b, node_a and node_c once each (all first visits)."""
    mod0.send_status_update(igt_ms=10_000, death_count=0)
    mod0.receive_until_type("leaderboard_update")
    for flag, igt in ((9000001, 20_000), (9000000, 30_000), (9000002, 40_000)):
        mod0.send_event_flag(flag, igt_ms=igt)
        mod0.receive_until_type("leaderboard_update")


def _kill(mod0, flag: int, igt: int) -> list[dict]:
    """Report a boss kill and return what the mod receives meanwhile.

    The kill is reported twice: the handler is sequential, so the second ACK
    arrives only after the first kill's hook (the grant) has run.
    """
    mod0.send_event_flag(flag, igt_ms=igt, message_id=igt)
    mod0.send_event_flag(flag, igt_ms=igt, message_id=igt + 1)
    seen = []
    for _ in range(20):
        msg = mod0.receive()
        seen.append(msg)
        if msg["type"] == "event_flag_ack" and msg["message_id"] == igt + 1:
            return seen
    raise AssertionError("no ACK for the barrier report")


def _of_type(messages: list[dict], msg_type: str) -> list[dict]:
    return [m for m in messages if m["type"] == msg_type]


def _player_row(integration_db, race_with_participants, index: int = 0) -> Participant:
    async def read():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_with_participants["race_id"]),
                    Participant.user_id == race_with_participants["players"][index]["user"].id,
                )
            )
            return result.scalar_one()

    return asyncio.run(read())


def _held_item(integration_db, race_with_participants, index: int = 0) -> dict | None:
    return _player_row(integration_db, race_with_participants, index).held_item


def _update_player(integration_db, race_with_participants, index: int = 0, **fields) -> None:
    async def write():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_with_participants["race_id"]),
                    Participant.user_id == race_with_participants["players"][index]["user"].id,
                )
            )
            participant = result.scalar_one()
            for name, value in fields.items():
                setattr(participant, name, value)
            await db.commit()

    asyncio.run(write())


@pytest.fixture
def force_key(monkeypatch):
    """Make the draw deterministic: return the chosen base key."""
    import speedfog_racing.websocket.race.items as items_module

    chosen = {"key": "hammer"}
    monkeypatch.setattr(items_module, "draw_base_key", lambda tier, weights, rng: chosen["key"])
    return chosen


def test_new_boss_kill_grants_an_item(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        grants = _of_type(_kill(mod0, BOSS_FLAG, 55_000), "item_grant")
    assert len(grants) == 1
    assert grants[0]["grant_id"] == 1
    assert grants[0]["item"] == "hammer"
    assert grants[0]["banner"] == {
        "icon": "hammer",
        "title": "Hammer",
        "line": "Everyone else fat-rolls for 20 s",
        "detail": "",
    }
    assert _held_item(integration_db, race_with_participants) == {
        "grant_id": 1,
        "item": "hammer",
        "confirmed": False,
    }


def test_item_received_confirms_the_grant(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        _kill(mod0, BOSS_FLAG, 55_000)
        # A stale id confirms nothing; the real one does.
        ws0.send_json({"type": "item_received", "grant_id": 99})
        ws0.send_json({"type": "item_received", "grant_id": 1})
        _kill(mod0, SECOND_BOSS_FLAG, 60_000)
    assert _held_item(integration_db, race_with_participants) == {
        "grant_id": 1,
        "item": "hammer",
        "confirmed": True,
    }


def test_kill_while_holding_grants_nothing(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        assert _of_type(_kill(mod0, BOSS_FLAG, 55_000), "item_grant")
        assert not _of_type(_kill(mod0, SECOND_BOSS_FLAG, 60_000), "item_grant")
        # Using the item frees the slot.
        mod0.send_event_flag(HAMMER["use_flag"], igt_ms=62_000, message_id=62_000)
        mod0.receive_until_type("item_result")
        grants = _of_type(_kill(mod0, THIRD_BOSS_FLAG, 65_000), "item_grant")
    assert [g["grant_id"] for g in grants] == [2]


def test_unconfirmed_grant_is_resent_on_reconnect(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        _kill(mod0, BOSS_FLAG, 55_000)

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12", drain=False)["type"] == "auth_ok"
        resent = mod0.receive_until_type("item_grant")
        assert resent["grant_id"] == 1
        assert resent["item"] == "hammer"
        ws0.send_json({"type": "item_received", "grant_id": 1})
        # Barrier: a status_update answer proves the confirmation was processed.
        _kill(mod0, BOSS_FLAG, 70_000)

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12", drain=False)["type"] == "auth_ok"
        seen = []
        while True:
            msg = mod0.receive()
            seen.append(msg)
            if msg["type"] == "leaderboard_update":
                break
    assert not _of_type(seen, "item_grant")


def test_unconfirmed_grant_is_resent_after_an_inventory_without_it(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        _kill(mod0, BOSS_FLAG, 55_000)

        ws0.send_json({"type": "item_inventory", "items": []})
        resent = _of_type(_barrier(mod0, 400), "item_grant")
        # Once the report holds it, the grant is confirmed and never sent again.
        ws0.send_json({"type": "item_inventory", "items": ["hammer"]})
        after_report = _barrier(mod0, 401)

    assert [(g["grant_id"], g["item"]) for g in resent] == [(1, "hammer")]
    assert not _of_type(after_report, "item_grant")
    assert _held_item(integration_db, race_with_participants) == {
        "grant_id": 1,
        "item": "hammer",
        "confirmed": True,
    }


def test_items_off_grants_nothing(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id, items=False)
    token = _start_race_and_connect(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth()["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        assert not _of_type(_kill(mod0, BOSS_FLAG, 55_000), "item_grant")
    assert _held_item(integration_db, race_with_participants) is None


def test_rune_pouch_variant_follows_progress(
    integration_client, race_with_participants, integration_db, force_key
):
    force_key["key"] = "rune_pouch"
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        grants = _of_type(_kill(mod0, BOSS_FLAG, 55_000), "item_grant")
    assert [g["item"] for g in grants] == ["rune_pouch_3"]


# ---------------------------------------------------------------------------
# Uses: a use flag resolves into effects, a result and shield blocks
# ---------------------------------------------------------------------------

RED_SHELL = {
    "name": "Red Shell",
    "icon": "red_shell",
    "goods_id": 1450803,
    "use_flag": 1050290103,
    "remove_flag": 1050290203,
    "effect_speffect": None,
    "duration_ms": None,
}
SHIELD = {
    "name": "Shield",
    "icon": "shield",
    "goods_id": 1450800,
    "use_flag": None,
    "remove_flag": 1050290200,
    "effect_speffect": None,
    "duration_ms": None,
}
USE_CATALOG = {"red_shell": RED_SHELL, "shield": SHIELD}
UNKNOWN_FLAG = 9999999


def _barrier(mod, message_id: int) -> list[dict]:
    """Send a flag the seed does not know and return every message up to its ACK.

    The handler is sequential: the ACK comes after every earlier message of
    this socket, hooks included, was processed.
    """
    mod.send_event_flag(UNKNOWN_FLAG, igt_ms=1, message_id=message_id)
    seen = []
    for _ in range(30):
        msg = mod.receive()
        seen.append(msg)
        if msg["type"] == "event_flag_ack" and msg["message_id"] == message_id:
            return seen
    raise AssertionError("no ACK for the barrier flag")


def _receive_until(mod, msg_type: str) -> list[dict]:
    seen = []
    for _ in range(30):
        msg = mod.receive()
        seen.append(msg)
        if msg["type"] == msg_type:
            return seen
    raise AssertionError(f"no {msg_type}")


def _put_two_runners_in_play(mod0, mod1) -> None:
    """Both runners playing, player 0 one layer ahead (node_a)."""
    mod0.send_status_update(igt_ms=10_000, death_count=0)
    mod1.send_status_update(igt_ms=10_000, death_count=0)
    mod0.send_event_flag(9000000, igt_ms=20_000, message_id=100)
    _receive_until(mod0, "event_flag_ack")
    _barrier(mod1, 101)


def _use_events(integration_db, race_id: str) -> list[RaceItemEvent]:
    async def read():
        async with integration_db() as db:
            result = await db.execute(
                select(RaceItemEvent).where(
                    RaceItemEvent.race_id == uuid.UUID(race_id), RaceItemEvent.kind == "use"
                )
            )
            return list(result.scalars().all())

    return asyncio.run(read())


def _held(item: str) -> dict:
    return {"grant_id": 1, "item": item, "confirmed": True}


def test_red_shell_hits_the_runner_ahead(
    integration_client, race_with_participants, integration_db, monkeypatch
):
    # The damage curve the expected payload and banners quote.
    monkeypatch.setattr(settings, "race_items_red_shell_pct", 20)
    monkeypatch.setattr(settings, "race_items_damage_floor_pct", 20)
    monkeypatch.setattr(settings, "race_items_damage_tail_pct", 5)
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    _patch_items_graph(integration_db, race_id, catalog=USE_CATALOG)
    _start_items_race(integration_client, race_with_participants)
    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.12")["type"] == "auth_ok"
        _put_two_runners_in_play(mod0, mod1)
        _update_player(integration_db, race_with_participants, 1, held_item=_held("red_shell"))
        history = _player_row(integration_db, race_with_participants, 1).zone_history

        mod1.send_event_flag(RED_SHELL["use_flag"], igt_ms=30_000, message_id=300)
        sender_seen = _receive_until(mod1, "event_flag_ack")
        effect = _receive_until(mod0, "item_effect")[-1]

    assert sender_seen[-1] == {"type": "event_flag_ack", "message_id": 300}
    assert effect == {
        "type": "item_effect",
        "item": "red_shell",
        "effect": {"kind": "damage", "base_pct": 20, "floor_pct": 20, "tail_pct": 5},
        "banner": {
            "icon": "red_shell",
            "title": "Red Shell",
            "line": "Hit for 20% HP",
            "detail": "from Player 1",
        },
        "reminder": None,
    }
    [result] = _of_type(sender_seen, "item_result")
    assert result["banner"]["line"] == "Hit Player 0"
    assert result["banner"]["detail"] == "20% HP"
    sender = _player_row(integration_db, race_with_participants, 1)
    assert sender.held_item is None
    assert sender.zone_history == history
    [event] = _use_events(integration_db, race_id)
    assert (event.item, event.igt_ms) == ("red_shell", 30_000)
    assert event.targets == [{"participant_id": players[0]["participant_id"], "outcome": "hit"}]


MUSHROOM = {
    "name": "Mushroom",
    "icon": "mushroom",
    "goods_id": 1450804,
    "use_flag": 1050290104,
    "remove_flag": 1050290204,
    "effect_speffect": None,
    "duration_ms": 30000,
}


def test_use_flag_is_acked_once_the_use_is_resolved(
    integration_client, race_with_participants, integration_db
):
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id, catalog={"mushroom": MUSHROOM})
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=10_000, death_count=0)
        _barrier(mod0, 100)
        _update_player(integration_db, race_with_participants, 0, held_item=_held("mushroom"))

        mod0.send_event_flag(MUSHROOM["use_flag"], igt_ms=30_000, message_id=300)
        seen = _receive_until(mod0, "event_flag_ack")
        # Read while the socket is open, right at the ACK.
        held = _held_item(integration_db, race_with_participants)
        events = _use_events(integration_db, race_id)

    # Without an ACK the mod replays the flag: it comes once the use is committed.
    assert [m["type"] for m in seen if m["type"] != "leaderboard_update"] == [
        "item_result",
        "event_flag_ack",
    ]
    assert seen[-1]["message_id"] == 300
    assert held is None
    assert [(e.item, e.igt_ms) for e in events] == [("mushroom", 30_000)]


def test_shield_blocks_and_is_removed(integration_client, race_with_participants, integration_db):
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    _patch_items_graph(integration_db, race_id, catalog=USE_CATALOG)
    _start_items_race(integration_client, race_with_participants)
    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.12")["type"] == "auth_ok"
        _put_two_runners_in_play(mod0, mod1)
        _update_player(integration_db, race_with_participants, 0, held_item=_held("shield"))
        _update_player(integration_db, race_with_participants, 1, held_item=_held("red_shell"))

        mod1.send_event_flag(RED_SHELL["use_flag"], igt_ms=30_000, message_id=300)
        result = _receive_until(mod1, "item_result")[-1]
        # Every message of the use reached player 0 before the sender's result.
        holder_seen = _barrier(mod0, 301)

    assert result["banner"]["line"] == "Blocked by Player 0's shield"
    assert _of_type(holder_seen, "item_effect") == []
    assert _of_type(holder_seen, "item_remove") == [
        {
            "type": "item_remove",
            "item": "shield",
            "banner": {
                "icon": "shield",
                "title": "Shield",
                "line": "Blocked Red Shell",
                "detail": "from Player 1",
            },
        }
    ]
    assert _held_item(integration_db, race_with_participants, 0) is None
    [event] = _use_events(integration_db, race_id)
    assert event.targets == [{"participant_id": players[0]["participant_id"], "outcome": "blocked"}]


def test_use_of_an_item_not_held_is_ignored(
    integration_client, race_with_participants, integration_db
):
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    _patch_items_graph(integration_db, race_id, catalog=USE_CATALOG)
    _start_items_race(integration_client, race_with_participants)
    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.12")["type"] == "auth_ok"
        _put_two_runners_in_play(mod0, mod1)
        _update_player(integration_db, race_with_participants, 1, held_item=_held("red_shell"))
        mod1.send_event_flag(RED_SHELL["use_flag"], igt_ms=30_000, message_id=300)
        _receive_until(mod1, "item_result")

        # The same use again, under a new message id: the item is gone.
        mod1.send_event_flag(RED_SHELL["use_flag"], igt_ms=31_000, message_id=301)
        sender_seen = _barrier(mod1, 302)
        target_seen = _barrier(mod0, 303)

    assert {"type": "event_flag_ack", "message_id": 301} in sender_seen
    assert not [m for m in sender_seen if m["type"].startswith("item_")]
    assert len(_of_type(target_seen, "item_effect")) == 1
    assert len(_use_events(integration_db, race_id)) == 1


def test_use_flag_on_a_race_with_items_off_is_acked_and_ignored(
    integration_client, race_with_participants, integration_db
):
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id, catalog=USE_CATALOG, items=False)
    token = _start_race_and_connect(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=10_000, death_count=0)
        _barrier(mod0, 100)
        _update_player(integration_db, race_with_participants, 0, held_item=_held("red_shell"))
        history = _player_row(integration_db, race_with_participants, 0).zone_history

        mod0.send_event_flag(RED_SHELL["use_flag"], igt_ms=30_000, message_id=300)
        seen = _barrier(mod0, 301)

    assert {"type": "event_flag_ack", "message_id": 300} in seen
    assert not [m for m in seen if m["type"].startswith("item_")]
    player = _player_row(integration_db, race_with_participants, 0)
    assert player.held_item == _held("red_shell")
    assert player.zone_history == history
    assert _use_events(integration_db, race_id) == []


def test_item_inventory_message_round_trip(
    integration_client, race_with_participants, integration_db
):
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id, catalog=USE_CATALOG)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.12")["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=10_000, death_count=0)
        _update_player(integration_db, race_with_participants, 0, held_item=_held("shield"))
        ws0.send_json({"type": "item_inventory", "items": ["red_shell", "shield"]})
        seen = _barrier(mod0, 400)

    removals = _of_type(seen, "item_remove")
    assert removals == [{"type": "item_remove", "item": "red_shell", "banner": None}]
    assert _held_item(integration_db, race_with_participants) == _held("shield")
