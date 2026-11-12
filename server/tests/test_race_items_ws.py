"""Race items on the mod socket: the capability gate, the catalog, the wire shapes."""

import asyncio
import json
import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Participant, Race
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


def _patch_items_graph(integration_db, race_id: str) -> None:
    """Make the race's seed carry the items plugin and set race_items on the race."""

    async def patch():
        async with integration_db() as db:
            result = await db.execute(
                select(Race).where(Race.id == uuid.UUID(race_id)).options(selectinload(Race.seed))
            )
            race = result.scalar_one()
            graph = json.loads(json.dumps(race.seed.graph_json))
            graph.setdefault("plugins", {})[RACE_ITEMS_PLUGIN] = {"enabled": True}
            graph[RACE_ITEMS_PLUGIN] = {"hammer": HAMMER}
            race.seed.graph_json = graph
            race.race_items = True
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


def _held_item(integration_db, race_with_participants) -> dict | None:
    async def read():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_with_participants["race_id"]),
                    Participant.user_id == race_with_participants["players"][0]["user"].id,
                )
            )
            return result.scalar_one().held_item

    return asyncio.run(read())


def _update_player0(integration_db, race_with_participants, **fields) -> None:
    async def write():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_with_participants["race_id"]),
                    Participant.user_id == race_with_participants["players"][0]["user"].id,
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
        # The item is used (cleared by hand until the use flow exists).
        _update_player0(integration_db, race_with_participants, held_item=None)
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
