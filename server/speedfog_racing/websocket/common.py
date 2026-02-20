"""Shared WebSocket utilities used by both race and training handlers."""

import asyncio
import json
import logging
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket

from speedfog_racing.services.grace_service import load_graces_mapping
from speedfog_racing.services.i18n import translate_zone_update
from speedfog_racing.services.layer_service import compute_zone_update
from speedfog_racing.websocket.schemas import AuthErrorMessage, ErrorMessage, PingMessage

logger = logging.getLogger(__name__)

HEARTBEAT_INTERVAL = 30.0  # seconds between pings
SEND_TIMEOUT = 5.0  # seconds before a send is considered failed
MOD_AUTH_TIMEOUT = 5.0  # seconds to wait for auth message


async def heartbeat_loop(
    websocket: WebSocket,
    *,
    interval: float = HEARTBEAT_INTERVAL,
    send_timeout: float = SEND_TIMEOUT,
) -> None:
    """Send periodic ping messages; close on failure so receive_text() raises."""
    ping_json = PingMessage().model_dump_json()
    try:
        while True:
            await asyncio.sleep(interval)
            await asyncio.wait_for(websocket.send_text(ping_json), timeout=send_timeout)
    except Exception:
        try:
            await websocket.close()
        except Exception:
            pass


async def send_auth_error(websocket: WebSocket, message: str) -> None:
    """Send auth error and close connection."""
    logger.warning("Auth error: %s", message)
    try:
        error = AuthErrorMessage(message=message)
        await websocket.send_text(error.model_dump_json())
        await websocket.close(code=4003, reason=message)
    except Exception:
        pass


async def send_error(
    websocket: WebSocket, message: str, *, send_timeout: float = SEND_TIMEOUT
) -> None:
    """Send a generic error message to the mod."""
    try:
        await asyncio.wait_for(
            websocket.send_text(ErrorMessage(message=message).model_dump_json()),
            timeout=send_timeout,
        )
    except Exception:
        pass


async def send_zone_update(
    websocket: WebSocket,
    node_id: str,
    graph_json: dict[str, Any],
    zone_history: list[dict[str, Any]] | None,
    locale: str = "en",
    *,
    send_timeout: float = SEND_TIMEOUT,
) -> None:
    """Send a zone_update unicast to the originating mod."""
    msg = compute_zone_update(node_id, graph_json, zone_history)
    if msg:
        msg = translate_zone_update(msg, locale)
        try:
            await asyncio.wait_for(websocket.send_text(json.dumps(msg)), timeout=send_timeout)
        except Exception:
            logger.warning("Failed to send zone_update")


_graces_mapping: dict[str, dict[str, Any]] | None = None


def get_graces_mapping() -> dict[str, dict[str, Any]]:
    """Lazily load and cache the graces mapping."""
    global _graces_mapping
    if _graces_mapping is None:
        _graces_mapping = load_graces_mapping()
    return _graces_mapping


def extract_event_ids(graph_json: dict[str, Any]) -> tuple[list[int], int | None]:
    """Extract sorted event_ids and finish_event from graph_json."""
    finish_event_id: int | None = None
    event_ids: list[int] = []

    event_map = graph_json.get("event_map", {})
    finish = graph_json.get("finish_event")
    if isinstance(finish, int):
        finish_event_id = finish
    if event_map:
        event_ids = sorted(int(k) for k in event_map.keys())
        if finish_event_id is not None and finish_event_id not in event_ids:
            event_ids.append(finish_event_id)

    return event_ids, finish_event_id


@dataclass
class ZoneQueryInput:
    """Parsed zone_query message fields."""

    grace_entity_id: int | None
    map_id: str | None
    position: tuple[Any, ...] | None
    play_region_id: int | None


def parse_zone_query_input(msg: dict[str, Any]) -> ZoneQueryInput | None:
    """Parse a zone_query message. Returns None if neither grace nor map_id present."""
    grace_entity_id = msg.get("grace_entity_id")
    if isinstance(grace_entity_id, int) and grace_entity_id != 0:
        pass  # valid
    else:
        grace_entity_id = None

    map_id_str = msg.get("map_id") if isinstance(msg.get("map_id"), str) else None

    if grace_entity_id is None and map_id_str is None:
        return None

    raw_pos = msg.get("position")
    position = tuple(raw_pos) if isinstance(raw_pos, list) and len(raw_pos) == 3 else None
    raw_pr = msg.get("play_region_id")
    play_region_id = raw_pr if isinstance(raw_pr, int) else None

    return ZoneQueryInput(
        grace_entity_id=grace_entity_id,
        map_id=map_id_str,
        position=position,
        play_region_id=play_region_id,
    )
