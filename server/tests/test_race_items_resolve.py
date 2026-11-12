"""Race item uses resolved by direct calls: targets, shields, misses and the item log."""

import asyncio
import uuid
from collections.abc import Callable

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from speedfog_racing.database import Base
from speedfog_racing.models import (
    Participant,
    ParticipantStatus,
    Race,
    RaceItemEvent,
    RaceStatus,
    Seed,
    SeedStatus,
    User,
)
from speedfog_racing.services.race_items import RACE_ITEMS_PLUGIN
from speedfog_racing.websocket.race.items import (
    ItemResolution,
    reconcile_inventory,
    resolve_item_use,
)
from speedfog_racing.websocket.race.manager import manager

pytestmark = pytest.mark.asyncio

PLAYING = ParticipantStatus.PLAYING


def _item(name: str, goods_id: int, *, use: bool = True, speffect=None, duration_ms=None) -> dict:
    return {
        "name": name,
        "icon": name.lower().replace(" ", "_"),
        "goods_id": goods_id,
        "use_flag": 1050290000 + goods_id % 100 if use else None,
        "remove_flag": 1050290500 + goods_id % 100,
        "effect_speffect": speffect,
        "duration_ms": duration_ms,
    }


GRAPH = {
    "total_layers": 5,
    "nodes": {},
    "plugins": {RACE_ITEMS_PLUGIN: {"enabled": True}},
    RACE_ITEMS_PLUGIN: {
        "shield": _item("Shield", 1450800, use=False),
        "red_shell": _item("Red Shell", 1450803),
        "mushroom": _item("Mushroom", 1450804, speffect=4000004, duration_ms=15000),
        "hammer": _item("Hammer", 1450805, speffect=4000005, duration_ms=15000),
        "blue_shell": _item("Blue Shell", 1450808, speffect=4000008, duration_ms=15000),
    },
}


@pytest.fixture
async def items_db():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    await engine.dispose()


async def _field(
    session_maker, *runners: tuple[str, ParticipantStatus, int, str | None]
) -> tuple[uuid.UUID, dict[str, uuid.UUID]]:
    """A running items race; each runner is (name, status, layer, held item key or None).

    A higher layer ranks first among playing runners.
    """
    tag = uuid.uuid4().hex[:8]
    async with session_maker() as db:
        organizer = User(twitch_id=f"org_{tag}", twitch_username=f"org_{tag}", api_token=tag)
        seed = Seed(
            seed_number=f"items_{tag}",
            pool_name="standard",
            graph_json=GRAPH,
            race_items=True,
            total_layers=5,
            folder_path=f"/test/items_{tag}",
            status=SeedStatus.CONSUMED,
        )
        db.add_all([organizer, seed])
        await db.flush()
        race = Race(
            name="Items",
            organizer_id=organizer.id,
            seed_id=seed.id,
            status=RaceStatus.RUNNING,
            race_items=True,
        )
        db.add(race)
        await db.flush()
        ids: dict[str, uuid.UUID] = {}
        for i, (name, status, layer, held) in enumerate(runners):
            user = User(
                twitch_id=f"{name}_{tag}",
                twitch_username=f"{name.lower()}_{tag}",
                twitch_display_name=name,
                api_token=f"{tag}_{i}",
            )
            db.add(user)
            await db.flush()
            participant = Participant(
                race_id=race.id,
                user_id=user.id,
                status=status,
                current_layer=layer,
                layer_entry_igts={str(layer): 1000},
                held_item={"grant_id": 1, "item": held, "confirmed": True} if held else None,
            )
            db.add(participant)
            await db.flush()
            ids[name] = participant.id
        await db.commit()
        return race.id, ids


async def _use(
    session_maker,
    race_id: uuid.UUID,
    sender: uuid.UUID,
    item_key: str,
    *,
    online: Callable[[uuid.UUID], bool] = lambda _: True,
) -> ItemResolution:
    return await resolve_item_use(
        session_maker, race_id, sender, item_key, 50_000, GRAPH, is_connected=online
    )


async def _held(session_maker, participant_id: uuid.UUID) -> dict | None:
    async with session_maker() as db:
        participant = await db.get(Participant, participant_id)
        assert participant is not None
        return participant.held_item


async def _use_events(session_maker, race_id: uuid.UUID) -> list[RaceItemEvent]:
    async with session_maker() as db:
        result = await db.execute(
            select(RaceItemEvent).where(
                RaceItemEvent.race_id == race_id, RaceItemEvent.kind == "use"
            )
        )
        return list(result.scalars().all())


async def test_group_item_misses_when_nobody_can_be_hit(items_db):
    # Nobody else is playing.
    race_id, ids = await _field(
        items_db,
        ("Alice", PLAYING, 2, "hammer"),
        ("Bob", ParticipantStatus.FINISHED, 5, None),
        ("Cleo", ParticipantStatus.ABANDONED, 3, None),
    )
    resolution = await _use(items_db, race_id, ids["Alice"], "hammer")
    assert resolution.result is not None
    assert resolution.result.banner.line == "Missed: no other runner"
    assert resolution.effects == []
    assert await _held(items_db, ids["Alice"]) is None
    [event] = await _use_events(items_db, race_id)
    assert event.targets == []

    # The others play but none is connected: the effects are dropped.
    race_id, ids = await _field(
        items_db,
        ("Alice", PLAYING, 2, "hammer"),
        ("Bob", PLAYING, 3, None),
        ("Cleo", PLAYING, 1, None),
    )
    resolution = await _use(
        items_db, race_id, ids["Alice"], "hammer", online=lambda pid: pid == ids["Alice"]
    )
    assert resolution.result is not None
    assert resolution.result.banner.line == "Missed"
    assert resolution.effects == []
    assert await _held(items_db, ids["Alice"]) is None
    [event] = await _use_events(items_db, race_id)
    assert event.targets == [
        {"participant_id": str(ids["Bob"]), "outcome": "offline"},
        {"participant_id": str(ids["Cleo"]), "outcome": "offline"},
    ]


async def test_mushroom_only_answers_the_sender(items_db):
    race_id, ids = await _field(
        items_db, ("Alice", PLAYING, 2, "mushroom"), ("Bob", PLAYING, 3, None)
    )
    resolution = await _use(items_db, race_id, ids["Alice"], "mushroom")
    assert resolution.effects == []
    assert resolution.removals == []
    assert resolution.result is not None
    assert resolution.result.banner.line == "Infinite stamina for 15 s"
    assert resolution.result.reminder is not None
    assert resolution.result.reminder.model_dump() == {
        "text": "Infinite stamina",
        "duration_ms": 15000,
    }
    assert await _held(items_db, ids["Alice"]) is None


async def test_an_offline_shield_holder_still_spends_the_shield(items_db):
    race_id, ids = await _field(
        items_db, ("Lea", PLAYING, 3, "shield"), ("Sam", PLAYING, 2, "red_shell")
    )
    resolution = await _use(
        items_db, race_id, ids["Sam"], "red_shell", online=lambda pid: pid == ids["Sam"]
    )
    assert resolution.result is not None
    assert resolution.result.banner.line == "Blocked by Lea's shield"
    assert [pid for pid, _ in resolution.removals] == [ids["Lea"]]
    assert await _held(items_db, ids["Lea"]) is None
    [event] = await _use_events(items_db, race_id)
    assert event.targets == [{"participant_id": str(ids["Lea"]), "outcome": "blocked"}]


async def test_concurrent_uses_consume_one_shield(items_db):
    race_id, ids = await _field(
        items_db,
        ("Lea", PLAYING, 3, "shield"),
        ("Sam", PLAYING, 2, "blue_shell"),
        ("Tom", PLAYING, 1, "blue_shell"),
    )
    # The handler resolves every use under the race room's items lock.
    lock = manager.get_or_create_room(race_id).items_lock

    async def use(sender: uuid.UUID) -> ItemResolution:
        async with lock:
            return await _use(items_db, race_id, sender, "blue_shell")

    try:
        resolutions = await asyncio.gather(use(ids["Sam"]), use(ids["Tom"]))
    finally:
        manager.rooms.pop(race_id, None)

    assert sum(len(r.removals) for r in resolutions) == 1
    assert sum(len(r.effects) for r in resolutions) == 1
    outcomes = sorted(t["outcome"] for e in await _use_events(items_db, race_id) for t in e.targets)
    assert outcomes == ["blocked", "hit"]
    assert await _held(items_db, ids["Lea"]) is None


async def _events(session_maker, race_id: uuid.UUID, kind: str) -> list[RaceItemEvent]:
    async with session_maker() as db:
        result = await db.execute(
            select(RaceItemEvent).where(
                RaceItemEvent.race_id == race_id, RaceItemEvent.kind == kind
            )
        )
        return list(result.scalars().all())


async def _set_held(session_maker, participant_id: uuid.UUID, held: dict | None) -> None:
    async with session_maker() as db:
        participant = await db.get(Participant, participant_id)
        assert participant is not None
        participant.held_item = held
        await db.commit()


async def test_reconcile_clears_a_lost_confirmed_item(items_db):
    race_id, ids = await _field(items_db, ("Alice", PLAYING, 2, "shield"))
    removals = await reconcile_inventory(items_db, ids["Alice"], [], GRAPH)
    assert removals == []
    assert await _held(items_db, ids["Alice"]) is None
    [event] = await _events(items_db, race_id, "lost")
    assert (event.participant_id, event.item) == (ids["Alice"], "shield")


async def test_reconcile_keeps_an_unconfirmed_grant(items_db):
    race_id, ids = await _field(items_db, ("Alice", PLAYING, 2, None))
    held = {"grant_id": 3, "item": "hammer", "confirmed": False}
    await _set_held(items_db, ids["Alice"], held)
    assert await reconcile_inventory(items_db, ids["Alice"], [], GRAPH) == []
    assert await _held(items_db, ids["Alice"]) == held
    assert await _events(items_db, race_id, "lost") == []


async def test_reconcile_confirms_a_reported_grant(items_db):
    _, ids = await _field(items_db, ("Alice", PLAYING, 2, None))
    await _set_held(items_db, ids["Alice"], {"grant_id": 3, "item": "hammer", "confirmed": False})
    assert await reconcile_inventory(items_db, ids["Alice"], ["hammer"], GRAPH) == []
    assert await _held(items_db, ids["Alice"]) == {
        "grant_id": 3,
        "item": "hammer",
        "confirmed": True,
    }


async def test_reconcile_takes_back_goods_not_held(items_db):
    race_id, ids = await _field(items_db, ("Alice", PLAYING, 2, "shield"))
    removals = await reconcile_inventory(
        items_db, ids["Alice"], ["hammer", "shield", "not_in_catalog"], GRAPH
    )
    assert [(r.item, r.banner) for r in removals] == [("hammer", None)]
    assert await _held(items_db, ids["Alice"]) == {
        "grant_id": 1,
        "item": "shield",
        "confirmed": True,
    }
    [event] = await _events(items_db, race_id, "take_back")
    assert event.item == "hammer"
    # Holding nothing, every reported item goes.
    _, ids = await _field(items_db, ("Bob", PLAYING, 2, None))
    removals = await reconcile_inventory(items_db, ids["Bob"], ["hammer", "hammer"], GRAPH)
    assert [r.item for r in removals] == ["hammer"]
