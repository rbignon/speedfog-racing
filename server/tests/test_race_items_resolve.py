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
from speedfog_racing.services.race_items import RACE_ITEMS_PLUGIN, shield_banner
from speedfog_racing.websocket.race.items import (
    ItemResolution,
    reconcile_inventory,
    resolve_item_use,
)
from speedfog_racing.websocket.race.manager import manager
from speedfog_racing.websocket.schemas import (
    ItemEffectMessage,
    ItemEffectPayload,
    ItemGrantMessage,
    ItemRemoveMessage,
)

pytestmark = pytest.mark.asyncio

PLAYING = ParticipantStatus.PLAYING


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


def _catalog(*items: tuple[str, dict], shield: bool = True) -> dict:
    """A graph.json 4.12 catalog: the Race Item goods holding ``items``, plus
    the Shield's own goods and item unless ``shield`` is False."""
    goods: dict[str, dict] = {
        "race_item": {
            "goods_id": 1450801,
            "use_flag": 1050290101,
            "remove_flag": 1050290201,
            "icon": "item_box",
            "icon_id": 60396,
        }
    }
    entries = dict(items)
    if shield:
        goods["shield"] = {
            "goods_id": 1450800,
            "use_flag": None,
            "remove_flag": 1050290200,
            "icon": "shield",
            "icon_id": 60385,
        }
        entries["shield"] = _item("Shield", 60385, goods="shield")
    return {"goods": goods, "items": entries}


GRAPH = {
    "total_layers": 5,
    "nodes": {},
    "plugins": {RACE_ITEMS_PLUGIN: {"enabled": True}},
    RACE_ITEMS_PLUGIN: _catalog(
        ("rune_pouch_2", _item("Rune Pouch", 60386, speffect=1450822)),
        ("red_shell", _item("Red Shell", 60388)),
        ("mushroom", _item("Mushroom", 60389, speffect=1450826, duration_ms=30000)),
        ("hammer", _item("Hammer", 60390, speffect=1450827, duration_ms=15000)),
        ("blue_shell", _item("Blue Shell", 60392, speffect=1450829, duration_ms=15000)),
        ("star", _item("Star", 60397, speffect=1450833, duration_ms=5000)),
    ),
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
    goods: str = "race_item",
    *,
    igt_ms: int = 50_000,
    online: Callable[[uuid.UUID], bool] = lambda _: True,
    star_until: dict[uuid.UUID, float] | None = None,
    now: float = 1000.0,
) -> ItemResolution:
    """The sender's mod reports the use flag of ``goods`` (the Race Item by default).

    Without ``star_until`` the use gets a window of its own, empty: pass the
    room's to carry a Star across uses."""
    return await resolve_item_use(
        session_maker,
        race_id,
        sender,
        goods,
        igt_ms,
        GRAPH,
        is_connected=online,
        star_until={} if star_until is None else star_until,
        now=now,
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
    resolution = await _use(items_db, race_id, ids["Alice"])
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
    resolution = await _use(items_db, race_id, ids["Alice"], online=lambda pid: pid == ids["Alice"])
    assert resolution.result is not None
    assert resolution.result.banner.line == "Missed"
    assert resolution.effects == []
    assert await _held(items_db, ids["Alice"]) is None
    [event] = await _use_events(items_db, race_id)
    assert event.targets == [
        {"participant_id": str(ids["Bob"]), "outcome": "offline"},
        {"participant_id": str(ids["Cleo"]), "outcome": "offline"},
    ]


async def test_race_item_use_resolves_the_held_item(items_db):
    race_id, ids = await _field(
        items_db,
        ("Alice", PLAYING, 2, "hammer"),
        ("Bob", PLAYING, 3, None),
        ("Cleo", PLAYING, 1, None),
    )
    # The use flag names the goods; the held item says what it does.
    resolution = await _use(items_db, race_id, ids["Alice"], "race_item")
    assert [(pid, e.item, e.effect.kind) for pid, e in resolution.effects] == [
        (ids["Bob"], "hammer", "equip_load"),
        (ids["Cleo"], "hammer", "equip_load"),
    ]
    assert resolution.result is not None
    assert (resolution.result.item, resolution.result.banner.line) == ("hammer", "Hit 2 runners")
    assert await _held(items_db, ids["Alice"]) is None
    [event] = await _use_events(items_db, race_id)
    assert event.item == "hammer"


async def test_mushroom_answers_its_own_mod_with_its_effect(items_db):
    race_id, ids = await _field(
        items_db, ("Alice", PLAYING, 2, "mushroom"), ("Bob", PLAYING, 3, None)
    )
    resolution = await _use(items_db, race_id, ids["Alice"])
    # The effect row goes to the sender's own mod, without a banner: the
    # result carries it, with the reminder.
    assert resolution.effects == [
        (
            ids["Alice"],
            ItemEffectMessage(
                item="mushroom",
                effect=ItemEffectPayload(kind="speffect", speffect_id=1450826, duration_ms=30000),
                banner=None,
                reminder=None,
            ),
        )
    ]
    assert resolution.removals == []
    assert resolution.result is not None
    assert resolution.result.banner.line == "Infinite stamina for 30s"
    assert resolution.result.reminder is not None
    assert resolution.result.reminder.model_dump() == {
        "text": "Infinite stamina",
        "duration_ms": 30000,
    }
    assert await _held(items_db, ids["Alice"]) is None
    [event] = await _use_events(items_db, race_id)
    assert event.targets == []


async def test_rune_pouch_answers_its_own_mod_with_its_effect(items_db):
    race_id, ids = await _field(
        items_db, ("Alice", PLAYING, 2, "rune_pouch_2"), ("Bob", PLAYING, 3, None)
    )
    resolution = await _use(items_db, race_id, ids["Alice"])
    assert [(pid, e.effect.model_dump(), e.banner) for pid, e in resolution.effects] == [
        (ids["Alice"], {"kind": "speffect", "speffect_id": 1450822}, None)
    ]
    assert resolution.result is not None
    assert resolution.result.banner.line == "Runes added"
    assert resolution.result.reminder is None


async def test_a_replayed_use_after_resolution_is_ignored(items_db):
    race_id, ids = await _field(
        items_db, ("Alice", PLAYING, 2, "red_shell"), ("Bob", PLAYING, 3, None)
    )
    first = await _use(items_db, race_id, ids["Alice"])
    assert first.result is not None
    # The ACK was lost: the mod reports the same use again.
    replay = await _use(items_db, race_id, ids["Alice"])
    assert (replay.result, replay.effects, replay.removals) == (None, [], [])
    assert len(await _use_events(items_db, race_id)) == 1


async def test_a_use_older_than_the_grant_is_ignored(items_db):
    race_id, ids = await _field(items_db, ("Alice", PLAYING, 2, None), ("Bob", PLAYING, 3, None))
    held = {"grant_id": 2, "item": "hammer", "confirmed": True, "igt_ms": 60_000}
    await _set_held(items_db, ids["Alice"], held)
    # Made before the kill that granted the hammer: the replay of an earlier
    # use (its ACK lost), which must not spend the new item.
    replay = await _use(items_db, race_id, ids["Alice"], igt_ms=50_000)
    assert (replay.result, replay.effects, replay.removals) == (None, [], [])
    assert await _held(items_db, ids["Alice"]) == held
    assert await _use_events(items_db, race_id) == []

    use = await _use(items_db, race_id, ids["Alice"], igt_ms=70_000)
    assert use.result is not None
    assert [(pid, e.item) for pid, e in use.effects] == [(ids["Bob"], "hammer")]
    assert await _held(items_db, ids["Alice"]) is None


async def test_a_goods_without_a_use_flag_is_never_used(items_db):
    race_id, ids = await _field(items_db, ("Lea", PLAYING, 3, "shield"), ("Sam", PLAYING, 2, None))
    # Neither the Shield's own goods (no use flag) nor the Race Item spends a held Shield.
    for goods in ("shield", "race_item"):
        resolution = await _use(items_db, race_id, ids["Lea"], goods)
        assert (resolution.result, resolution.effects, resolution.removals) == (None, [], [])
    assert await _held(items_db, ids["Lea"]) == {"grant_id": 1, "item": "shield", "confirmed": True}
    assert await _use_events(items_db, race_id) == []


async def test_shield_block_removes_the_shield_goods(items_db):
    race_id, ids = await _field(
        items_db, ("Lea", PLAYING, 3, "shield"), ("Sam", PLAYING, 2, "red_shell")
    )
    resolution = await _use(items_db, race_id, ids["Sam"])
    assert resolution.removals == [
        (ids["Lea"], ItemRemoveMessage(goods="shield", banner=shield_banner("Red Shell", "Sam")))
    ]
    assert resolution.effects == []
    assert await _held(items_db, ids["Lea"]) is None


async def test_an_offline_shield_holder_still_spends_the_shield(items_db):
    race_id, ids = await _field(
        items_db, ("Lea", PLAYING, 3, "shield"), ("Sam", PLAYING, 2, "red_shell")
    )
    resolution = await _use(items_db, race_id, ids["Sam"], online=lambda pid: pid == ids["Sam"])
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
            return await _use(items_db, race_id, sender)

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


async def test_missing_goods_clears_a_confirmed_item(items_db):
    race_id, ids = await _field(items_db, ("Alice", PLAYING, 2, "hammer"))
    # The Shield's goods is no sign of the hammer, held as the Race Item.
    removals = await reconcile_inventory(items_db, ids["Alice"], ["shield"], GRAPH)
    assert [(r.goods, r.banner) for r in removals] == [("shield", None)]
    assert await _held(items_db, ids["Alice"]) is None
    [event] = await _events(items_db, race_id, "lost")
    assert (event.participant_id, event.item) == (ids["Alice"], "hammer")


async def test_reconcile_keeps_and_resends_an_unconfirmed_grant(items_db):
    race_id, ids = await _field(items_db, ("Alice", PLAYING, 2, None))
    held = {"grant_id": 3, "item": "hammer", "confirmed": False}
    await _set_held(items_db, ids["Alice"], held)
    messages = await reconcile_inventory(items_db, ids["Alice"], ["shield"], GRAPH)
    # Its goods may not be spawned yet: the grant goes again, after the take-backs.
    assert [m.type for m in messages] == ["item_remove", "item_grant"]
    assert isinstance(messages[1], ItemGrantMessage)
    assert (messages[1].grant_id, messages[1].item) == (3, "hammer")
    assert await _held(items_db, ids["Alice"]) == held
    assert await _events(items_db, race_id, "lost") == []


async def test_present_goods_confirm_and_resend_an_unconfirmed_grant(items_db):
    race_id, ids = await _field(items_db, ("Alice", PLAYING, 2, None))
    await _set_held(items_db, ids["Alice"], {"grant_id": 3, "item": "hammer", "confirmed": False})
    # The Race Item may be another item's copy: the grant tells the mod it now
    # holds the hammer (the mod skips the spawn, the goods being there).
    messages = await reconcile_inventory(items_db, ids["Alice"], ["race_item"], GRAPH)
    assert [(type(m), m.grant_id, m.item) for m in messages] == [(ItemGrantMessage, 3, "hammer")]
    assert await _held(items_db, ids["Alice"]) == {
        "grant_id": 3,
        "item": "hammer",
        "confirmed": True,
    }
    # Confirmed: the next report holding it sends nothing.
    assert await reconcile_inventory(items_db, ids["Alice"], ["race_item"], GRAPH) == []
    assert await _events(items_db, race_id, "take_back") == []


async def test_reconcile_takes_back_goods_not_held(items_db):
    race_id, ids = await _field(items_db, ("Alice", PLAYING, 2, "shield"))
    removals = await reconcile_inventory(
        items_db, ids["Alice"], ["race_item", "shield", "not_in_catalog"], GRAPH
    )
    assert [(r.goods, r.banner) for r in removals] == [("race_item", None)]
    assert await _held(items_db, ids["Alice"]) == {
        "grant_id": 1,
        "item": "shield",
        "confirmed": True,
    }
    [event] = await _events(items_db, race_id, "take_back")
    assert event.item == "race_item"


async def test_reported_goods_without_a_held_item_is_taken_back(items_db):
    race_id, ids = await _field(items_db, ("Bob", PLAYING, 2, None))
    removals = await reconcile_inventory(items_db, ids["Bob"], ["race_item", "race_item"], GRAPH)
    assert removals == [ItemRemoveMessage(goods="race_item", banner=None)]
    [event] = await _events(items_db, race_id, "take_back")
    assert (event.participant_id, event.item) == (ids["Bob"], "race_item")


async def test_a_star_blocks_without_spending_the_shield(items_db):
    race_id, ids = await _field(
        items_db,
        ("Ann", PLAYING, 4, "star"),
        ("Bea", PLAYING, 3, "red_shell"),
        ("Cy", PLAYING, 2, "hammer"),
    )
    star_until: dict[uuid.UUID, float] = {}
    use = await _use(items_db, race_id, ids["Ann"], star_until=star_until, now=1000.0)
    assert [(pid, e.effect.model_dump()) for pid, e in use.effects] == [
        (ids["Ann"], {"kind": "speffect", "speffect_id": 1450833, "duration_ms": 5000})
    ]
    assert star_until == {ids["Ann"]: 1005.0}
    # Ann holds a Shield too (the Star left her slot free).
    await _set_held(items_db, ids["Ann"], {"grant_id": 2, "item": "shield", "confirmed": True})

    red = await _use(items_db, race_id, ids["Bea"], star_until=star_until, now=1003.0)
    hammer = await _use(items_db, race_id, ids["Cy"], star_until=star_until, now=1004.0)
    for resolution in (red, hammer):
        assert [(pid, n.banner.title, n.banner.detail) for pid, n in resolution.notices] == [
            (ids["Ann"], "Star", "from " + ("Bea" if resolution is red else "Cy"))
        ]
        assert resolution.removals == []
    assert red.effects == []
    assert [n.banner.line for _, n in red.notices] == ["Blocked Red Shell"]
    assert [n.banner.line for _, n in hammer.notices] == ["Blocked Hammer"]
    # The hammer still hits Bea.
    assert [pid for pid, _ in hammer.effects] == [ids["Bea"]]
    assert red.result is not None and red.result.banner.line == "Blocked by Ann's Star"
    assert hammer.result is not None and hammer.result.banner.line == "Hit Bea, 1 blocked"
    assert await _held(items_db, ids["Ann"]) == {
        "grant_id": 2,
        "item": "shield",
        "confirmed": True,
    }
    events = await _use_events(items_db, race_id)
    assert [
        t["outcome"]
        for e in events[1:]
        for t in e.targets
        if t["participant_id"] == str(ids["Ann"])
    ] == [
        "blocked",
        "blocked",
    ]

    # After the window the Shield is spent as usual.
    await _set_held(items_db, ids["Bea"], {"grant_id": 3, "item": "red_shell", "confirmed": True})
    later = await _use(items_db, race_id, ids["Bea"], star_until=star_until, now=1005.5)
    assert later.notices == []
    assert [pid for pid, _ in later.removals] == [ids["Ann"]]
    assert await _held(items_db, ids["Ann"]) is None


async def test_a_star_window_is_per_runner_and_expires(items_db):
    race_id, ids = await _field(
        items_db,
        ("Ann", PLAYING, 4, "star"),
        ("Bea", PLAYING, 3, "hammer"),
        ("Cy", PLAYING, 2, None),
    )
    star_until: dict[uuid.UUID, float] = {}
    await _use(items_db, race_id, ids["Ann"], star_until=star_until, now=200.0)
    assert star_until == {ids["Ann"]: 205.0}
    # Exactly at the deadline the window is over; Bea and Cy never had one.
    hit = await _use(items_db, race_id, ids["Bea"], star_until=star_until, now=205.0)
    assert hit.notices == []
    assert sorted(pid for pid, _ in hit.effects) == sorted([ids["Ann"], ids["Cy"]])
