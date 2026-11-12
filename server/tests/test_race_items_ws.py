"""Race items on the mod socket: the capability gate, the catalog, the wire shapes."""

import asyncio
import json
import uuid

from sqlalchemy import select
from sqlalchemy.orm import selectinload

from speedfog_racing.models import Race
from speedfog_racing.services.race_items import RACE_ITEMS_PLUGIN
from speedfog_racing.websocket.schemas import (
    RACE_ITEMS_OLD_MOD_MESSAGE,
    ItemBanner,
    ItemEffectMessage,
    ItemEffectPayload,
)

from . import test_integration as _integration
from .test_integration import ModTestClient

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
