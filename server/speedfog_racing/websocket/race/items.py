"""Race items: granting an item after a boss kill and confirming it.

The functions open their own sessions and never touch a socket: the handler
calls them under the race's ``items_lock`` and sends what they return.
"""

import logging
import random
import uuid
from collections.abc import Mapping
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from sqlalchemy.orm import selectinload

from speedfog_racing.config import settings
from speedfog_racing.models import Participant, ParticipantStatus, Race, RaceItemEvent
from speedfog_racing.services.race_items import (
    draw_base_key,
    extract_race_item_catalog,
    grant_banner,
    rune_pouch_variant,
    tier_of,
)
from speedfog_racing.websocket.race.manager import sort_leaderboard
from speedfog_racing.websocket.schemas import ItemGrantMessage

logger = logging.getLogger(__name__)


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
        result = await db.execute(
            select(Race)
            .where(Race.id == race_id)
            .options(selectinload(Race.participants).selectinload(Participant.user))
        )
        race = result.scalar_one_or_none()
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
