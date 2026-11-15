"""Race items: granting an item after a boss kill, confirming it and resolving a use.

The functions open their own sessions and never touch a socket: the handler
calls them under the race's ``items_lock`` and sends what they return.
"""

import logging
import random
import time
import uuid
from collections.abc import Callable, Mapping, MutableMapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.config import settings
from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceItemEvent
from speedfog_racing.services.race_items import (
    ITEM_RULES,
    Runner,
    available_base_keys,
    base_key,
    draw_base_key,
    draw_camera_variant,
    effect_payload,
    extract_race_item_catalog,
    grant_banner,
    item_order,
    reminder_for,
    resolve_targets,
    result_banner,
    rune_pouch_variant,
    shield_banner,
    star_banner,
    target_banner,
    tier_of,
)
from speedfog_racing.websocket.race.manager import leaderboard_gaps, sort_leaderboard
from speedfog_racing.websocket.schemas import (
    ItemEffectMessage,
    ItemGrantMessage,
    ItemNoticeMessage,
    ItemRemoveMessage,
    ItemResultMessage,
)

logger = logging.getLogger(__name__)


async def _load_race(db: AsyncSession, race_id: uuid.UUID) -> Race | None:
    """The race and its field (participants with their users)."""
    result = await db.execute(
        select(Race)
        .where(Race.id == race_id)
        .options(selectinload(Race.participants).selectinload(Participant.user))
    )
    return result.scalar_one_or_none()


def item_standings(
    participants: Sequence[Participant], graph_json: Mapping[str, Any]
) -> list[Participant]:
    """The playing runners in race item order (``item_order``), the leader first."""
    graph = dict(graph_json)
    ordered, entry_igts = sort_leaderboard(participants, graph_json=graph)
    gaps = leaderboard_gaps(ordered, entry_igts, graph)
    by_id = {p.id: p for p in participants}
    playing = [p.id for p in ordered if p.status == ParticipantStatus.PLAYING]
    return [by_id[pid] for pid in item_order(playing, gaps, settings.race_items_igt_lead_s * 1000)]


async def grant_item(
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    participant_id: uuid.UUID,
    graph_json: Mapping[str, Any],
    *,
    igt_ms: int,
    rng: random.Random | None = None,
) -> ItemGrantMessage | None:
    """Draw an item for a runner who just killed a boss and record it as held.

    ``igt_ms`` is the kill's IGT, kept with the held item: a use older than
    its grant is a replay (see ``resolve_item_use``). Returns the message to
    send, or None when the race has items off, the runner is not playing,
    already holds an item, or the drawn key is missing from the seed's catalog.
    """
    async with session_maker() as db:
        race = await _load_race(db, race_id)
        if race is None or not race.race_items:
            return None
        me = next((p for p in race.participants if p.id == participant_id), None)
        if me is None or me.status != ParticipantStatus.PLAYING or me.held_item:
            return None

        playing = item_standings(race.participants, graph_json)
        index = next((i for i, p in enumerate(playing) if p.id == participant_id), None)
        if index is None:
            return None

        catalog = extract_race_item_catalog(graph_json)
        tier = tier_of(index, len(playing))
        key = draw_base_key(
            tier,
            settings.race_items_tier_weights,
            available_base_keys(catalog.items),
            rng if rng is not None else random.Random(),
        )
        if key is None:
            logger.warning("race item draw: nothing to draw: race=%s tier=%s", race_id, tier)
            return None
        if key == "rune_pouch":
            key = rune_pouch_variant(me.current_layer, int(graph_json.get("total_layers") or 0))
        entry = catalog.items.get(key)
        if entry is None:
            logger.warning("Race item %s drawn but absent from the catalog: race=%s", key, race_id)
            return None

        me.item_grant_count += 1
        grant_id = me.item_grant_count
        me.held_item = {"grant_id": grant_id, "item": key, "confirmed": False, "igt_ms": igt_ms}
        db.add(
            RaceItemEvent(
                race_id=race_id,
                participant_id=participant_id,
                kind="grant",
                item=key,
                igt_ms=igt_ms,
            )
        )
        await db.commit()
        return ItemGrantMessage(grant_id=grant_id, item=key, banner=grant_banner(key, entry))


async def confirm_grant(
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    grant_id: int,
) -> None:
    """Mark the held item confirmed when ``grant_id`` is the held grant."""
    async with session_maker() as db:
        participant = await db.get(Participant, participant_id)
        held = participant.held_item if participant else None
        if participant is None or not held or held.get("grant_id") != grant_id:
            return
        if held.get("confirmed"):
            return
        # Reassign: a JSON column does not see in-place changes.
        participant.held_item = {**held, "confirmed": True}
        await db.commit()


def pending_grant_message(
    participant: Participant, graph_json: Mapping[str, Any] | None
) -> ItemGrantMessage | None:
    """The grant message for a held, unconfirmed item (re-sent until confirmed)."""
    held = participant.held_item
    if not held or held.get("confirmed") or graph_json is None:
        return None
    entry = extract_race_item_catalog(graph_json).items.get(held["item"])
    if entry is None:
        return None
    return ItemGrantMessage(
        grant_id=held["grant_id"], item=held["item"], banner=grant_banner(held["item"], entry)
    )


@dataclass
class ItemResolution:
    """What a use sends: per target an effect or, for a shield holder, the
    shield's removal or, for a Star holder, a notice, and the sender's result
    (None when the use is ignored)."""

    result: ItemResultMessage | None = None
    effects: list[tuple[uuid.UUID, ItemEffectMessage]] = field(default_factory=list)
    removals: list[tuple[uuid.UUID, ItemRemoveMessage]] = field(default_factory=list)
    notices: list[tuple[uuid.UUID, ItemNoticeMessage]] = field(default_factory=list)


async def resolve_item_use(
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    participant_id: uuid.UUID,
    goods_key: str,
    igt_ms: int,
    graph_json: Mapping[str, Any],
    *,
    is_connected: Callable[[uuid.UUID], bool],
    star_until: MutableMapping[uuid.UUID, float] | None = None,
    now: float | None = None,
    rng: random.Random | None = None,
) -> ItemResolution:
    """Consume the runner's held item and resolve it on its targets.

    ``goods_key`` is the goods whose use flag the mod reported (the Race
    Item, whatever item it holds). Empty unless the runner holds an item of
    that goods, and a goods without a use flag (the Shield) is never used: a
    replayed or stray use changes nothing. A use older in IGT than the held
    item's grant (``held_item["igt_ms"]``, 0 when absent) was made before the
    kill that granted it: the replay of an earlier use, ignored too, so it
    never spends an item granted since. Targets come from the playing
    runners in item order. A runner whose ``star_until`` (``time.monotonic()``
    deadline, set when they use a Star) is still ahead of ``now`` is blocked
    first: nothing is spent and a Shield stays, the holder gets an
    ``item_notice``. A held shield blocks the item and is spent,
    connected or not; a target without a connected mod is a miss. A self item
    sends its effect, without a banner, to the sender's own mod. Logs one
    ``use`` event with every target's outcome.
    """
    if star_until is None:
        star_until = {}
    if now is None:
        now = time.monotonic()
    catalog = extract_race_item_catalog(graph_json)
    goods = catalog.goods.get(goods_key)
    shield = catalog.items.get("shield")
    async with session_maker() as db:
        race = await _load_race(db, race_id)
        sender = (
            next((p for p in race.participants if p.id == participant_id), None) if race else None
        )
        held = sender.held_item if sender else None
        item_key = held.get("item") if held else None
        entry = catalog.items.get(item_key) if isinstance(item_key, str) else None
        if (
            race is None
            or sender is None
            or not isinstance(item_key, str)
            or entry is None
            or entry.goods != goods_key
            or goods is None
            or goods.use_flag is None
        ):
            logger.info(
                "Race item use ignored (not held): race=%s participant=%s goods=%s held=%s",
                race_id,
                participant_id,
                goods_key,
                item_key,
            )
            return ItemResolution()
        granted_at = int(held.get("igt_ms") or 0) if held else 0
        if igt_ms < granted_at:
            logger.info(
                "Race item use ignored (older than its grant, a replay): race=%s "
                "participant=%s item=%s igt_ms=%d grant_igt_ms=%d",
                race_id,
                participant_id,
                item_key,
                igt_ms,
                granted_at,
            )
            return ItemResolution()
        rule = ITEM_RULES.get(base_key(item_key))
        if rule is None:
            logger.warning("Race item %s used but unknown: race=%s", item_key, race_id)
            return ItemResolution()

        sender.held_item = None
        sender_name = sender.user.twitch_display_name or sender.user.twitch_username
        by_id = {p.id: p for p in race.participants}
        resolution = ItemResolution()
        hits: list[str] = []
        blocked: list[str] = []
        stars: list[str] = []
        offline = 0
        variant = draw_camera_variant(rng) if rule.effect == "camera" else None
        outcomes: list[dict[str, str]] = []
        if rule.target == "self":
            payload = effect_payload(item_key, entry)
            if base_key(item_key) == "star" and entry.duration_ms is not None:
                star_until[participant_id] = now + entry.duration_ms / 1000
            if payload is not None:
                # Applied without a banner: the result carries it.
                resolution.effects.append(
                    (
                        participant_id,
                        ItemEffectMessage(
                            item=item_key, effect=payload, banner=None, reminder=None
                        ),
                    )
                )
        else:
            playing = [
                Runner(p.id, p.user.twitch_display_name or p.user.twitch_username)
                for p in item_standings(race.participants, graph_json)
            ]
            payload = effect_payload(item_key, entry, variant)
            for runner in resolve_targets(rule.target, participant_id, playing):
                target = by_id[runner.participant_id]
                # A Blue Shell used while leading hits its own sender.
                own = runner.participant_id == participant_id
                target_held = target.held_item
                if star_until.get(target.id, 0.0) > now:
                    resolution.notices.append(
                        (target.id, ItemNoticeMessage(banner=star_banner(entry.name, sender_name)))
                    )
                    stars.append(runner.name)
                    outcome = "blocked"
                elif shield is not None and target_held and target_held.get("item") == "shield":
                    target.held_item = None
                    resolution.removals.append(
                        (
                            target.id,
                            ItemRemoveMessage(
                                goods=shield.goods, banner=shield_banner(entry.name, sender_name)
                            ),
                        )
                    )
                    blocked.append(runner.name)
                    outcome = "blocked"
                elif payload is not None and is_connected(target.id):
                    resolution.effects.append(
                        (
                            target.id,
                            ItemEffectMessage(
                                item=item_key,
                                effect=payload,
                                banner=target_banner(
                                    item_key, entry, "yourself" if own else sender_name, variant
                                ),
                                reminder=reminder_for(item_key, entry, variant),
                            ),
                        )
                    )
                    hits.append("yourself" if own else runner.name)
                    outcome = "hit"
                else:
                    offline += 1
                    outcome = "offline"
                outcomes.append({"participant_id": str(target.id), "outcome": outcome})

        resolution.result = ItemResultMessage(
            item=item_key,
            banner=result_banner(item_key, entry, hits, blocked, offline, stars, variant),
            # Only a self item affects its sender.
            reminder=reminder_for(item_key, entry) if rule.target == "self" else None,
        )
        db.add(
            RaceItemEvent(
                race_id=race_id,
                participant_id=participant_id,
                kind="use",
                item=item_key,
                igt_ms=igt_ms,
                targets=outcomes,
            )
        )
        await db.commit()
        return resolution


async def reconcile_inventory(
    session_maker: async_sessionmaker[AsyncSession],
    participant_id: uuid.UUID,
    goods: Sequence[str],
    graph_json: Mapping[str, Any],
) -> list[ItemRemoveMessage | ItemGrantMessage]:
    """Align the held item with the race goods the mod reports in the inventory.

    The report is the truth about the goods in the game, and the held item
    shows as its goods (the Race Item or the Shield). A held item whose goods
    is reported is confirmed; a confirmed one whose goods is absent was lost
    (save reload, drop) and is cleared, logging ``lost``, so the runner can
    draw again; an unconfirmed one whose goods is absent is kept, its goods
    may not be spawned yet. An unconfirmed item gets its grant returned last
    to be sent again, present or not: items share a goods, so the copy
    reported may stand for another item, and the grant tells the mod which
    one it holds (the mod skips the spawn of a goods it has, and ignores a
    grant id it already has). Every other reported goods is not held: it is
    returned as a removal without banner and logged ``take_back`` (the goods
    key as the item). Keys outside the catalog's goods are ignored.
    """
    catalog = extract_race_item_catalog(graph_json)
    reported = [key for key in dict.fromkeys(goods) if key in catalog.goods]
    async with session_maker() as db:
        participant = await db.get(Participant, participant_id)
        if participant is None:
            return []
        held = participant.held_item
        held_key = held.get("item") if held else None
        held_entry = catalog.items.get(held_key) if isinstance(held_key, str) else None
        held_goods = held_entry.goods if held_entry else None
        # Built before the confirmation below: a confirmed item has no pending grant.
        pending = pending_grant_message(participant, graph_json)
        if held and held_goods in reported:
            if not held.get("confirmed"):
                # Reassign: a JSON column does not see in-place changes.
                participant.held_item = {**held, "confirmed": True}
        elif held and held.get("confirmed"):
            participant.held_item = None
            db.add(
                RaceItemEvent(
                    race_id=participant.race_id,
                    participant_id=participant_id,
                    kind="lost",
                    item=held_key,
                    igt_ms=participant.igt_ms,
                )
            )
        messages: list[ItemRemoveMessage | ItemGrantMessage] = []
        for key in reported:
            if key == held_goods:
                continue
            messages.append(ItemRemoveMessage(goods=key))
            db.add(
                RaceItemEvent(
                    race_id=participant.race_id,
                    participant_id=participant_id,
                    kind="take_back",
                    item=key,
                    igt_ms=participant.igt_ms,
                )
            )
        if pending is not None:
            messages.append(pending)
        await db.commit()
        return messages
