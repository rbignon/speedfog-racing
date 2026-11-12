"""Race items: granting an item after a boss kill, confirming it and resolving a use.

The functions open their own sessions and never touch a socket: the handler
calls them under the race's ``items_lock`` and sends what they return.
"""

import logging
import random
import uuid
from collections.abc import Callable, Mapping, Sequence
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
    base_key,
    draw_base_key,
    effect_payload,
    extract_race_item_catalog,
    grant_banner,
    reminder_for,
    resolve_targets,
    result_banner,
    rune_pouch_variant,
    shield_banner,
    target_banner,
    tier_of,
)
from speedfog_racing.websocket.race.manager import sort_leaderboard
from speedfog_racing.websocket.schemas import (
    ItemEffectMessage,
    ItemGrantMessage,
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


async def grant_item(
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    participant_id: uuid.UUID,
    graph_json: Mapping[str, Any],
    *,
    rng: random.Random | None = None,
) -> ItemGrantMessage | None:
    """Draw an item for a runner who just killed a boss and record it as held.

    Returns the message to send, or None when the race has items off, the
    runner is not playing, already holds an item, or the drawn key is missing
    from the seed's catalog.
    """
    async with session_maker() as db:
        race = await _load_race(db, race_id)
        if race is None or not race.race_items:
            return None
        me = next((p for p in race.participants if p.id == participant_id), None)
        if me is None or me.status != ParticipantStatus.PLAYING or me.held_item:
            return None

        ordered, _ = sort_leaderboard(race.participants, graph_json=dict(graph_json))
        playing = [p for p in ordered if p.status == ParticipantStatus.PLAYING]
        index = next((i for i, p in enumerate(playing) if p.id == participant_id), None)
        if index is None:
            return None

        key = draw_base_key(
            tier_of(index, len(playing)),
            settings.race_items_weights,
            rng if rng is not None else random.Random(),
        )
        if key == "rune_pouch":
            key = rune_pouch_variant(me.current_layer, int(graph_json.get("total_layers") or 0))
        entry = extract_race_item_catalog(graph_json).get(key)
        if entry is None:
            logger.warning("Race item %s drawn but absent from the catalog: race=%s", key, race_id)
            return None

        me.item_grant_count += 1
        grant_id = me.item_grant_count
        me.held_item = {"grant_id": grant_id, "item": key, "confirmed": False}
        db.add(
            RaceItemEvent(
                race_id=race_id,
                participant_id=participant_id,
                kind="grant",
                item=key,
                igt_ms=me.igt_ms,
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
    """The grant message for a held, unconfirmed item (re-sent at auth)."""
    held = participant.held_item
    if not held or held.get("confirmed") or graph_json is None:
        return None
    entry = extract_race_item_catalog(graph_json).get(held["item"])
    if entry is None:
        return None
    return ItemGrantMessage(
        grant_id=held["grant_id"], item=held["item"], banner=grant_banner(held["item"], entry)
    )


@dataclass
class ItemResolution:
    """What a use sends: per target an effect or, for a shield holder, the
    shield's removal, and the sender's result (None when the use is ignored)."""

    result: ItemResultMessage | None = None
    effects: list[tuple[uuid.UUID, ItemEffectMessage]] = field(default_factory=list)
    removals: list[tuple[uuid.UUID, ItemRemoveMessage]] = field(default_factory=list)


async def resolve_item_use(
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    participant_id: uuid.UUID,
    item_key: str,
    igt_ms: int,
    graph_json: Mapping[str, Any],
    *,
    is_connected: Callable[[uuid.UUID], bool],
) -> ItemResolution:
    """Consume the runner's held item and resolve it on its targets.

    Empty unless the runner holds exactly ``item_key``: a replayed or stray
    use changes nothing. Targets come from the playing runners in leaderboard
    order. A held shield blocks the item and is spent, connected or not; a
    target without a connected mod is a miss. A self item answers the sender
    only. Logs one ``use`` event with every target's outcome.
    """
    async with session_maker() as db:
        race = await _load_race(db, race_id)
        sender = (
            next((p for p in race.participants if p.id == participant_id), None) if race else None
        )
        held = sender.held_item if sender else None
        if race is None or sender is None or not held or held.get("item") != item_key:
            logger.info(
                "Race item use ignored (not held): race=%s participant=%s item=%s held=%s",
                race_id,
                participant_id,
                item_key,
                held.get("item") if held else None,
            )
            return ItemResolution()
        entry = extract_race_item_catalog(graph_json).get(item_key)
        rule = ITEM_RULES.get(base_key(item_key))
        if entry is None or rule is None:
            logger.warning("Race item %s used but unknown: race=%s", item_key, race_id)
            return ItemResolution()

        sender.held_item = None
        sender_name = sender.user.twitch_display_name or sender.user.twitch_username
        by_id = {p.id: p for p in race.participants}
        resolution = ItemResolution()
        hits: list[str] = []
        blocked: list[str] = []
        offline = 0
        outcomes: list[dict[str, str]] = []
        if rule.target != "self":
            ordered, _ = sort_leaderboard(race.participants, graph_json=dict(graph_json))
            playing: list[Runner] = []
            for p in ordered:
                if p.status == ParticipantStatus.PLAYING:
                    user = by_id[p.id].user
                    playing.append(Runner(p.id, user.twitch_display_name or user.twitch_username))
            payload = effect_payload(item_key, entry)
            for runner in resolve_targets(rule.target, participant_id, playing):
                target = by_id[runner.participant_id]
                target_held = target.held_item
                if target_held and target_held.get("item") == "shield":
                    target.held_item = None
                    resolution.removals.append(
                        (
                            target.id,
                            ItemRemoveMessage(
                                item="shield", banner=shield_banner(entry.name, sender_name)
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
                                banner=target_banner(item_key, entry, sender_name),
                                reminder=reminder_for(item_key, entry),
                            ),
                        )
                    )
                    hits.append(runner.name)
                    outcome = "hit"
                else:
                    offline += 1
                    outcome = "offline"
                outcomes.append({"participant_id": str(target.id), "outcome": outcome})

        resolution.result = ItemResultMessage(
            item=item_key,
            banner=result_banner(item_key, entry, hits, blocked, offline),
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
    items: Sequence[str],
    graph_json: Mapping[str, Any],
) -> list[ItemRemoveMessage]:
    """Align the held item with the race items the mod reports in the inventory.

    The report is the truth about the goods in the game. A held item in the
    report is confirmed; a confirmed one that is absent was lost (save reload,
    drop) and is cleared, logging ``lost``, so the runner can draw again; an
    unconfirmed one that is absent is kept, its goods may not be spawned yet.
    Every other reported item is not held: it is returned as a removal
    without banner and logged ``take_back``. Keys outside the catalog are
    ignored.
    """
    catalog = extract_race_item_catalog(graph_json)
    reported = [key for key in dict.fromkeys(items) if key in catalog]
    async with session_maker() as db:
        participant = await db.get(Participant, participant_id)
        if participant is None:
            return []
        held = participant.held_item
        held_key = held.get("item") if held else None
        if held and held_key in reported:
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
        removals: list[ItemRemoveMessage] = []
        for key in reported:
            if key == held_key:
                continue
            removals.append(ItemRemoveMessage(item=key))
            db.add(
                RaceItemEvent(
                    race_id=participant.race_id,
                    participant_id=participant_id,
                    kind="take_back",
                    item=key,
                    igt_ms=participant.igt_ms,
                )
            )
        await db.commit()
        return removals
