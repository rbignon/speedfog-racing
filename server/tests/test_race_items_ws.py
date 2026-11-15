"""Race items on the mod socket: the capability gate, the catalog, the wire shapes."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from speedfog_racing.config import settings
from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceItemEvent
from speedfog_racing.services.race_items import RACE_ITEMS_PLUGIN
from speedfog_racing.websocket.schemas import (
    RACE_ITEMS_OLD_MOD_MESSAGE,
    ItemBanner,
    ItemEffectMessage,
    ItemEffectPayload,
    RaceItemCatalogWire,
    RaceItemGoodsWire,
    RaceItemWire,
)

from . import test_integration as _integration
from .test_integration import BOSS_FLAG, ModTestClient, _patch_boss_graph, _start_race_and_connect

# The race fixtures of the integration suite, reused as they are.
integration_db = _integration.integration_db
integration_client = _integration.integration_client
race_with_participants = _integration.race_with_participants
seed_folder = _integration.seed_folder

RACE_ITEM = {
    "goods_id": 1450801,
    "use_flag": 1050290101,
    "remove_flag": 1050290201,
    "icon": "item_box",
    "icon_id": 60396,
}
SHIELD_GOODS = {
    "goods_id": 1450800,
    "use_flag": None,
    "remove_flag": 1050290200,
    "icon": "shield",
    "icon_id": 60385,
}
# The Race Item's use flag: the only use flag, whatever item is held.
USE_FLAG = RACE_ITEM["use_flag"]


def _item(
    name: str, icon_id: int, *, goods: str = "race_item", speffect=None, duration_ms=None
) -> dict:
    return {
        "name": name,
        "icon": name.lower().replace(" ", "_"),
        "icon_id": icon_id,
        "goods": goods,
        "effect_speffect": speffect,
        "duration_ms": duration_ms,
    }


SHIELD = _item("Shield", 60385, goods="shield")
HAMMER = _item("Hammer", 60390, speffect=1450827, duration_ms=20000)


def _catalog(*items: tuple[str, dict], shield: bool = True) -> dict:
    """A graph.json 4.12 catalog: the Race Item goods holding ``items``, plus
    the Shield's own goods and item unless ``shield`` is False."""
    goods = {"race_item": RACE_ITEM}
    entries = dict(items)
    if shield:
        goods["shield"] = SHIELD_GOODS
        entries["shield"] = SHIELD
    return {"goods": goods, "items": entries}


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
            graph[RACE_ITEMS_PLUGIN] = (
                catalog if catalog is not None else _catalog(("hammer", HAMMER), shield=False)
            )
            race.seed.graph_json = graph
            race.race_items = items
            await db.commit()

    asyncio.run(patch())


# A race without items: a 1.12 mod reads the field as a map of items, which
# `{"goods": {}, "items": {}}` would break (two items missing every field).
EMPTY_CATALOG: dict[str, object] = {}


# 1.12 spoke the per-item goods (it would spawn nothing of the catalog); 1.13
# reads the catalog but neither times the effects across loads nor holds an Ink
# on `unused_exits`; 1.14 knows none of the memory effects nor `item_notice`.
@pytest.mark.parametrize("protocol_version", ["1.12", "1.13", "1.14"])
def test_a_mod_before_1_15_is_refused_on_an_items_race(
    integration_client, race_with_participants, integration_db, protocol_version
):
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id)
    token = race_with_participants["players"][0]["mod_token"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        response = ModTestClient(ws, token).auth(protocol_version=protocol_version)
    assert response["type"] == "auth_error"
    assert response["message"] == RACE_ITEMS_OLD_MOD_MESSAGE


def test_items_race_accepts_1_15(integration_client, race_with_participants, integration_db):
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id, catalog=_catalog(("hammer", HAMMER)))
    token = race_with_participants["players"][0]["mod_token"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        response = ModTestClient(ws, token).auth(protocol_version="1.15")
    assert response["type"] == "auth_ok"
    assert response["seed"]["race_item_catalog"] == {
        "goods": {
            "race_item": {
                "goods_id": 1450801,
                "use_flag": 1050290101,
                "remove_flag": 1050290201,
                "icon_id": 60396,
            },
            "shield": {
                "goods_id": 1450800,
                "use_flag": None,
                "remove_flag": 1050290200,
                "icon_id": 60385,
            },
        },
        "items": {
            "hammer": {"name": "Hammer", "icon": "hammer", "icon_id": 60390, "goods": "race_item"},
            "shield": {"name": "Shield", "icon": "shield", "icon_id": 60385, "goods": "shield"},
        },
    }
    assert response["race"]["race_items"] is True
    assert response["held_item"] is None


def test_plain_race_sends_an_empty_catalog_and_accepts_old_mods(
    integration_client, race_with_participants
):
    race_id = race_with_participants["race_id"]
    token = race_with_participants["players"][0]["mod_token"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        response = ModTestClient(ws, token).auth(protocol_version="1.11")
    assert response["type"] == "auth_ok"
    assert response["seed"]["race_item_catalog"] == EMPTY_CATALOG
    assert response["held_item"] is None


def test_auth_ok_carries_the_held_item_and_the_catalog(
    integration_client, race_with_participants, integration_db
):
    race_id = race_with_participants["race_id"]
    token = race_with_participants["players"][0]["mod_token"]
    _patch_items_graph(integration_db, race_id)
    # Confirmed or not: a restarted mod restores the icon and the held row from it.
    for confirmed in (True, False):
        held = {"grant_id": 1, "item": "hammer", "confirmed": confirmed}
        _update_player(integration_db, race_with_participants, 0, held_item=held)
        with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
            response = ModTestClient(ws, token).auth(protocol_version="1.15")
        assert response["held_item"] == "hammer"
        catalog = response["seed"]["race_item_catalog"]
        assert catalog["goods"]["race_item"]["icon_id"] == 60396
        assert catalog["items"]["hammer"]["goods"] == "race_item"

    # Items off: the mod holds nothing, whatever the row says.
    _patch_items_graph(integration_db, race_id, items=False)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws:
        response = ModTestClient(ws, token).auth(protocol_version="1.15")
    assert response["held_item"] is None


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
        assert mod0.auth(protocol_version="1.15")["seed"]["race_item_catalog"] == EMPTY_CATALOG
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.12")["type"] == "auth_ok"
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
        response = mod0.auth(protocol_version="1.15")
        assert response["race"]["race_items"] is True
        assert response["seed"]["race_item_catalog"]["items"]["hammer"]["goods"] == "race_item"
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1:
        response = ModTestClient(ws1, players[1]["mod_token"]).auth(protocol_version="1.12")
        assert response["type"] == "auth_error"
        assert response["message"] == RACE_ITEMS_OLD_MOD_MESSAGE

    # Switching back off closes the mods too; they get an empty catalog again.
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        switch(False)
        assert _expect_close(mod0) == 1000
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        response = ModTestClient(ws0, players[0]["mod_token"]).auth(protocol_version="1.15")
        assert response["seed"]["race_item_catalog"] == EMPTY_CATALOG


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


def test_race_item_catalog_dumps_empty_as_an_empty_object():
    assert json.loads(RaceItemCatalogWire().model_dump_json()) == {}
    # A catalog with goods keeps both keys, an empty one included.
    goods_only = RaceItemCatalogWire(
        goods={"shield": RaceItemGoodsWire(goods_id=1450800, remove_flag=1050290200, icon_id=60385)}
    )
    assert json.loads(goods_only.model_dump_json()) == {
        "goods": {
            "shield": {
                "goods_id": 1450800,
                "use_flag": None,
                "remove_flag": 1050290200,
                "icon_id": 60385,
            }
        },
        "items": {},
    }
    full = RaceItemCatalogWire(
        goods=goods_only.goods,
        items={"shield": RaceItemWire(name="Shield", icon="shield", icon_id=60385, goods="shield")},
    )
    assert set(json.loads(full.model_dump_json())) == {"goods", "items"}


# ---------------------------------------------------------------------------
# Grants: a new boss kill hands out an item
# ---------------------------------------------------------------------------

SECOND_BOSS_FLAG = 10000801
THIRD_BOSS_FLAG = 10000802


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
            graph[RACE_ITEMS_PLUGIN] = _catalog(
                ("hammer", HAMMER),
                ("rune_pouch_1", _item("Rune Pouch", 60386, speffect=1450821)),
                ("rune_pouch_2", _item("Rune Pouch", 60386, speffect=1450822)),
                ("rune_pouch_3", _item("Rune Pouch", 60386, speffect=1450823)),
            )
            race.seed.graph_json = graph
            race.race_items = items
            await db.commit()

    asyncio.run(patch())


def _start_items_race(integration_client, race_with_participants) -> str:
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
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
    monkeypatch.setattr(
        items_module, "draw_base_key", lambda tier, weights, available, rng: chosen["key"]
    )
    return chosen


def test_new_boss_kill_grants_an_item(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
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
    # The grant keeps the kill's IGT: a use older than it is a replay.
    assert _held_item(integration_db, race_with_participants) == {
        "grant_id": 1,
        "item": "hammer",
        "confirmed": False,
        "igt_ms": 55_000,
    }


def test_item_received_confirms_the_grant(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
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
        "igt_ms": 55_000,
    }


def test_kill_while_holding_grants_nothing(
    integration_client, race_with_participants, integration_db, force_key
):
    race_id = race_with_participants["race_id"]
    _patch_grant_graph(integration_db, race_id)
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        assert _of_type(_kill(mod0, BOSS_FLAG, 55_000), "item_grant")
        assert not _of_type(_kill(mod0, SECOND_BOSS_FLAG, 60_000), "item_grant")
        # Using the item frees the slot.
        mod0.send_event_flag(USE_FLAG, igt_ms=62_000, message_id=62_000)
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
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        _kill(mod0, BOSS_FLAG, 55_000)

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.15", drain=False)["type"] == "auth_ok"
        resent = mod0.receive_until_type("item_grant")
        assert resent["grant_id"] == 1
        assert resent["item"] == "hammer"
        ws0.send_json({"type": "item_received", "grant_id": 1})
        # Barrier: a status_update answer proves the confirmation was processed.
        _kill(mod0, BOSS_FLAG, 70_000)

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.15", drain=False)["type"] == "auth_ok"
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
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        _kill(mod0, BOSS_FLAG, 55_000)

        ws0.send_json({"type": "item_inventory", "goods": []})
        resent = _of_type(_barrier(mod0, 400), "item_grant")
        # The report holding its goods confirms it, with the grant once more
        # (the copy may stand for another item); then it is never sent again.
        ws0.send_json({"type": "item_inventory", "goods": ["race_item"]})
        confirming = _of_type(_barrier(mod0, 401), "item_grant")
        ws0.send_json({"type": "item_inventory", "goods": ["race_item"]})
        after_report = _barrier(mod0, 402)

    assert [(g["grant_id"], g["item"]) for g in resent] == [(1, "hammer")]
    assert [(g["grant_id"], g["item"]) for g in confirming] == [(1, "hammer")]
    assert not _of_type(after_report, "item_grant")
    assert _held_item(integration_db, race_with_participants) == {
        "grant_id": 1,
        "item": "hammer",
        "confirmed": True,
        "igt_ms": 55_000,
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
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        _walk_three_arenas(mod0)
        grants = _of_type(_kill(mod0, BOSS_FLAG, 55_000), "item_grant")
    assert [g["item"] for g in grants] == ["rune_pouch_3"]


# ---------------------------------------------------------------------------
# Uses: a use flag resolves into effects, a result and shield blocks
# ---------------------------------------------------------------------------

RED_SHELL = _item("Red Shell", 60388)
USE_CATALOG = _catalog(("red_shell", RED_SHELL))
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
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.15")["type"] == "auth_ok"
        _put_two_runners_in_play(mod0, mod1)
        _update_player(integration_db, race_with_participants, 1, held_item=_held("red_shell"))
        history = _player_row(integration_db, race_with_participants, 1).zone_history

        mod1.send_event_flag(USE_FLAG, igt_ms=30_000, message_id=300)
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


BLUE_SHELL = _item("Blue Shell", 60392, speffect=1450829, duration_ms=15000)


def test_blue_shell_used_while_leading_hits_its_sender(
    integration_client, race_with_participants, integration_db
):
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    _patch_items_graph(integration_db, race_id, catalog=_catalog(("blue_shell", BLUE_SHELL)))
    _start_items_race(integration_client, race_with_participants)
    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.15")["type"] == "auth_ok"
        # Player 0 leads (one layer ahead) and holds the Blue Shell.
        _put_two_runners_in_play(mod0, mod1)
        _update_player(integration_db, race_with_participants, 0, held_item=_held("blue_shell"))

        mod0.send_event_flag(USE_FLAG, igt_ms=30_000, message_id=300)
        sender_seen = _receive_until(mod0, "event_flag_ack")
        other_seen = _barrier(mod1, 301)

    [effect] = _of_type(sender_seen, "item_effect")
    assert effect["effect"] == {
        "kind": "speffect",
        "speffect_id": 1450829,
        "duration_ms": 15000,
    }
    assert effect["banner"] == {
        "icon": "blue_shell",
        "title": "Blue Shell",
        "line": "Max HP halved for 15 s",
        "detail": "from yourself",
    }
    [result] = _of_type(sender_seen, "item_result")
    assert (result["banner"]["line"], result["banner"]["detail"]) == ("Hit yourself", "15 s")
    assert _of_type(other_seen, "item_effect") == []
    [event] = _use_events(integration_db, race_id)
    assert event.targets == [{"participant_id": players[0]["participant_id"], "outcome": "hit"}]


def _leads_in_igt_on_a_shallower_layer(integration_db, race_with_participants, **holder) -> None:
    """Player 0 a layer deeper (the leaderboard leader), player 1 ahead in IGT.

    Player 1 entered layer 1 at 20 s of IGT, 80 s before player 0 did: time
    lost outside IGT left it behind on the board, not in the race. ``holder``
    goes to player 0's row (a held item).
    """
    _update_player(
        integration_db,
        race_with_participants,
        0,
        status=ParticipantStatus.PLAYING,
        current_layer=2,
        igt_ms=160_000,
        layer_entry_igts={"0": 0, "1": 100_000, "2": 150_000},
        zone_history=[
            {"node_id": "start_node", "igt_ms": 0, "type": "spawn"},
            {"node_id": "node_a", "igt_ms": 100_000, "type": "fog"},
            {"node_id": "node_b", "igt_ms": 150_000, "type": "fog"},
        ],
        **holder,
    )
    _update_player(
        integration_db,
        race_with_participants,
        1,
        status=ParticipantStatus.PLAYING,
        current_layer=1,
        igt_ms=60_000,
        layer_entry_igts={"0": 0, "1": 20_000},
        zone_history=[
            {"node_id": "start_node", "igt_ms": 0, "type": "spawn"},
            {"node_id": "node_a", "igt_ms": 20_000, "type": "fog"},
        ],
    )


@pytest.mark.parametrize("lead_s,line", [(60, "Hit Player 1"), (90, "Missed: nobody ahead")])
def test_items_rank_a_runner_ahead_in_igt_above_a_deeper_one(
    integration_client, race_with_participants, integration_db, monkeypatch, lead_s, line
):
    monkeypatch.setattr(settings, "race_items_igt_lead_s", lead_s)
    race_id = race_with_participants["race_id"]
    players = race_with_participants["players"]
    _patch_items_graph(integration_db, race_id, catalog=USE_CATALOG)
    _start_items_race(integration_client, race_with_participants)
    with (
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0,
        integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws1,
    ):
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.15")["type"] == "auth_ok"
        _put_two_runners_in_play(mod0, mod1)
        _leads_in_igt_on_a_shallower_layer(
            integration_db, race_with_participants, held_item=_held("red_shell")
        )

        mod0.send_event_flag(USE_FLAG, igt_ms=160_000, message_id=300)
        [result] = _of_type(_receive_until(mod0, "event_flag_ack"), "item_result")

    assert result["banner"]["line"] == line


def test_the_draw_tier_follows_the_item_order(race_with_participants, integration_db, monkeypatch):
    import speedfog_racing.websocket.race.items as items_module

    tiers: list[str] = []
    monkeypatch.setattr(
        items_module,
        "draw_base_key",
        lambda tier, weights, available, rng: tiers.append(tier) or "red_shell",
    )
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id, catalog=USE_CATALOG)
    _leads_in_igt_on_a_shallower_layer(integration_db, race_with_participants)

    async def grant(index: int):
        async with integration_db() as db:
            result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(selectinload(Race.seed))
            )
            graph = result.scalar_one().seed.graph_json
        participant_id = uuid.UUID(race_with_participants["players"][index]["participant_id"])
        return await items_module.grant_item(
            integration_db, uuid.UUID(race_id), participant_id, graph, igt_ms=60_000
        )

    # Two runners: the first in item order draws front items, the other back
    # ones. Player 1 ranks first, although a layer behind on the board.
    assert asyncio.run(grant(1)) is not None
    assert asyncio.run(grant(0)) is not None
    assert tiers == ["front", "back"]


def test_an_empty_tier_grants_nothing(race_with_participants, integration_db, monkeypatch, caplog):
    import speedfog_racing.websocket.race.items as items_module
    from speedfog_racing.config import settings
    from speedfog_racing.models import Participant, RaceItemEvent

    monkeypatch.setattr(settings, "race_items_tier_weights", {"front": {}, "back": {}})
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id, catalog=USE_CATALOG)
    _leads_in_igt_on_a_shallower_layer(integration_db, race_with_participants)
    participant_id = uuid.UUID(race_with_participants["players"][1]["participant_id"])

    async def run():
        async with integration_db() as db:
            result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(selectinload(Race.seed))
            )
            graph = result.scalar_one().seed.graph_json
        with caplog.at_level("INFO"):
            granted = await items_module.grant_item(
                integration_db, uuid.UUID(race_id), participant_id, graph, igt_ms=60_000
            )
        async with integration_db() as db:
            participant = await db.get(Participant, participant_id)
            events = (await db.execute(select(RaceItemEvent))).scalars().all()
            return granted, participant.item_grant_count, participant.held_item, list(events)

    granted, count, held, events = asyncio.run(run())
    assert granted is None
    assert count == 0
    assert not held
    assert events == []
    assert "nothing to draw" in caplog.text


MUSHROOM = _item("Mushroom", 60389, speffect=1450826, duration_ms=30000)


def test_use_flag_is_acked_once_the_use_is_resolved(
    integration_client, race_with_participants, integration_db
):
    race_id = race_with_participants["race_id"]
    _patch_items_graph(integration_db, race_id, catalog=_catalog(("mushroom", MUSHROOM)))
    token = _start_items_race(integration_client, race_with_participants)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, token)
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=10_000, death_count=0)
        _barrier(mod0, 100)
        _update_player(integration_db, race_with_participants, 0, held_item=_held("mushroom"))

        mod0.send_event_flag(USE_FLAG, igt_ms=30_000, message_id=300)
        seen = _receive_until(mod0, "event_flag_ack")
        # Read while the socket is open, right at the ACK.
        held = _held_item(integration_db, race_with_participants)
        events = _use_events(integration_db, race_id)

    # Without an ACK the mod replays the flag: it comes once the use is committed.
    # A self item's effect goes to the sender's own mod, its banner on the result.
    assert [m["type"] for m in seen if m["type"] != "leaderboard_update"] == [
        "item_effect",
        "item_result",
        "event_flag_ack",
    ]
    [effect] = _of_type(seen, "item_effect")
    assert effect == {
        "type": "item_effect",
        "item": "mushroom",
        "effect": {"kind": "speffect", "speffect_id": 1450826, "duration_ms": 30000},
        "banner": None,
        "reminder": None,
    }
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
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.15")["type"] == "auth_ok"
        _put_two_runners_in_play(mod0, mod1)
        _update_player(integration_db, race_with_participants, 0, held_item=_held("shield"))
        _update_player(integration_db, race_with_participants, 1, held_item=_held("red_shell"))

        mod1.send_event_flag(USE_FLAG, igt_ms=30_000, message_id=300)
        result = _receive_until(mod1, "item_result")[-1]
        # Every message of the use reached player 0 before the sender's result.
        holder_seen = _barrier(mod0, 301)

    assert result["banner"]["line"] == "Blocked by Player 0's shield"
    assert _of_type(holder_seen, "item_effect") == []
    assert _of_type(holder_seen, "item_remove") == [
        {
            "type": "item_remove",
            "goods": "shield",
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
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        mod1 = ModTestClient(ws1, players[1]["mod_token"])
        assert mod1.auth(protocol_version="1.15")["type"] == "auth_ok"
        _put_two_runners_in_play(mod0, mod1)
        _update_player(integration_db, race_with_participants, 1, held_item=_held("red_shell"))
        mod1.send_event_flag(USE_FLAG, igt_ms=30_000, message_id=300)
        _receive_until(mod1, "item_result")

        # The same use again, under a new message id: the item is gone.
        mod1.send_event_flag(USE_FLAG, igt_ms=31_000, message_id=301)
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

        mod0.send_event_flag(USE_FLAG, igt_ms=30_000, message_id=300)
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
        assert mod0.auth(protocol_version="1.15")["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=10_000, death_count=0)
        _update_player(integration_db, race_with_participants, 0, held_item=_held("shield"))
        ws0.send_json({"type": "item_inventory", "goods": ["race_item", "shield"]})
        seen = _barrier(mod0, 400)

    removals = _of_type(seen, "item_remove")
    assert removals == [{"type": "item_remove", "goods": "race_item", "banner": None}]
    assert _held_item(integration_db, race_with_participants) == _held("shield")
