"""Base WebSocket handler classes and shared utilities.

Module-level pure functions and constants (moved from common.py and race/mod.py),
plus three base classes: BaseHandler, BaseModHandler, BaseSpectatorHandler.
"""

import asyncio
import json
import logging
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Generic, Protocol, TypeVar

from fastapi import WebSocket, WebSocketDisconnect
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from speedfog_racing.services.grace_service import load_graces_mapping, resolve_zone_query
from speedfog_racing.services.i18n import translate_zone_update
from speedfog_racing.services.layer_service import compute_zone_update, get_start_node
from speedfog_racing.websocket.schemas import (
    AuthErrorMessage,
    ErrorMessage,
    EventFlagAckMessage,
    PingMessage,
    ZoneQueryAckMessage,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
HEARTBEAT_INTERVAL = 30.0  # seconds between pings
SEND_TIMEOUT = 5.0  # seconds before a send is considered failed
MOD_AUTH_TIMEOUT = 5.0  # seconds to wait for auth message
MAX_FRESH_IGT_MS = 15_000  # 15s: fresh save reaches first load screen at ~3-5s
MAX_IGT_MS = 86_400_000  # 24 hours
MAX_DEATH_COUNT = 10_000
MAX_ZONE_HISTORY = 1000  # 1000 event flags allocated per seed
MSG_RATE_WINDOW = 10.0  # sliding window in seconds
MSG_RATE_LIMIT = 200  # max messages per window (normal mod sends ~2/s)

# Shared entrances (DuplicateEntrance in FogMod) inject multiple SetEventFlag
# instructions for the same warp, all resolving to the same node_id via event_map.
# The mod sends each flag as a separate WebSocket message within a single frame,
# so they arrive with near-identical IGT. This tolerance window deduplicates them.
SHARED_ENTRANCE_DEDUP_MS = 1000


# ---------------------------------------------------------------------------
# MessageRateLimiter
# ---------------------------------------------------------------------------
@dataclass
class MessageRateLimiter:
    """Sliding window rate limiter for WebSocket messages."""

    window: float = MSG_RATE_WINDOW
    limit: int = MSG_RATE_LIMIT
    _timestamps: deque[float] = field(init=False, default_factory=deque)

    def check(self) -> bool:
        """Record a message and return True if within limit, False if exceeded."""
        now = time.monotonic()
        cutoff = now - self.window
        while self._timestamps and self._timestamps[0] < cutoff:
            self._timestamps.popleft()
        self._timestamps.append(now)
        return len(self._timestamps) <= self.limit


# ---------------------------------------------------------------------------
# ZoneQueryInput
# ---------------------------------------------------------------------------
@dataclass
class ZoneQueryInput:
    """Parsed zone_query message fields."""

    grace_entity_id: int | None
    map_id: str | None
    position: tuple[Any, ...] | None
    play_region_id: int | None
    igt_ms: int | None
    message_id: int | None


# ---------------------------------------------------------------------------
# Pure functions
# ---------------------------------------------------------------------------
def clamp_igt(value: object) -> int | None:
    """Validate and return igt_ms, or None if out of range."""
    if not isinstance(value, int):
        return None
    if not (0 <= value <= MAX_IGT_MS):
        logger.warning("igt_ms out of range: %s", value)
        return None
    return value


def clamp_death_count(value: object) -> int | None:
    """Validate and return death_count, or None if out of range."""
    if not isinstance(value, int):
        return None
    if not (0 <= value <= MAX_DEATH_COUNT):
        logger.warning("death_count out of range: %s", value)
        return None
    return value


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
        logger.debug("Heartbeat failed, closing connection")
        try:
            await websocket.close()
        except Exception:
            pass


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


def attribute_deaths(
    zone_history: list[dict[str, Any]],
    current_zone: str,
    delta: int,
) -> list[dict[str, Any]]:
    """Attribute death delta to the most recent visit of current_zone.

    Deep-copies entries so mutations don't affect the committed state.
    SQLAlchemy compares new vs committed to detect dirt.
    Returns a new list suitable for JSON column assignment.
    """
    history = [dict(e) for e in zone_history]
    for entry in reversed(history):
        if entry.get("node_id") == current_zone:
            entry["deaths"] = entry.get("deaths", 0) + delta
            break
    return history


def is_shared_entrance_duplicate(history: list[dict[str, Any]], node_id: str, igt: int) -> bool:
    """Check if this event flag is a duplicate from shared entrance multi-flag injection."""
    return bool(
        history
        and history[-1].get("node_id") == node_id
        and abs(history[-1].get("igt_ms", 0) - igt) <= SHARED_ENTRANCE_DEDUP_MS
    )


def detect_layer_jump(
    graph_json: dict[str, Any],
    zone_history: list[dict[str, Any]],
    new_node_id: str,
) -> tuple[str, int, int, list[str]] | None:
    """Detect an event_flag that skips layers relative to the previous entry.

    Fog gates always traverse from layer N to layer N+1 by design. If a new
    event_flag produces an entry whose layer is not ``last.layer + 1``, a
    backtrack entry was probably missed (for example a respawn inside a
    previously-traversed node that the zone_query resolver could not localize)
    or there is a bug in event_map resolution.

    Returns ``(last_node_id, last_layer, new_layer, bridge_candidates)`` when a
    jump is detected, ``None`` otherwise. ``bridge_candidates`` lists
    already-visited graph neighbors of ``new_node_id`` at ``new_layer - 1``,
    i.e. plausible missed-backtrack nodes, for diagnostic logging.
    """
    if not zone_history:
        return None
    last_node_id = zone_history[-1].get("node_id")
    if not isinstance(last_node_id, str) or last_node_id == new_node_id:
        return None
    nodes = graph_json.get("nodes", {})
    last_node = nodes.get(last_node_id)
    new_node = nodes.get(new_node_id)
    if not isinstance(last_node, dict) or not isinstance(new_node, dict):
        return None
    last_layer = last_node.get("layer")
    new_layer = new_node.get("layer")
    if not isinstance(last_layer, int) or not isinstance(new_layer, int):
        return None
    if new_layer == last_layer + 1:
        return None
    neighbors: set[str] = set()
    for edge in graph_json.get("edges", []):
        if not isinstance(edge, dict):
            continue
        src = edge.get("from")
        dst = edge.get("to")
        if dst == new_node_id and isinstance(src, str):
            neighbors.add(src)
        elif src == new_node_id and isinstance(dst, str):
            neighbors.add(dst)
    explored = {
        entry.get("node_id") for entry in zone_history if isinstance(entry.get("node_id"), str)
    }
    bridges = sorted(
        n
        for n in neighbors
        if n in explored
        and isinstance(nodes.get(n), dict)
        and nodes[n].get("layer") == new_layer - 1
    )
    return (last_node_id, last_layer, new_layer, bridges)


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
    igt_ms = clamp_igt(msg.get("igt_ms"))

    raw_message_id = msg.get("message_id")
    message_id = raw_message_id if isinstance(raw_message_id, int) else None

    return ZoneQueryInput(
        grace_entity_id=grace_entity_id,
        map_id=map_id_str,
        position=position,
        play_region_id=play_region_id,
        igt_ms=igt_ms,
        message_id=message_id,
    )


_graces_mapping: dict[str, dict[str, Any]] | None = None


def get_graces_mapping() -> dict[str, dict[str, Any]]:
    """Lazily load and cache the graces mapping."""
    global _graces_mapping  # noqa: PLW0603
    if _graces_mapping is None:
        _graces_mapping = load_graces_mapping()
    return _graces_mapping


# ---------------------------------------------------------------------------
# Protocol for mod entity (Participant or TrainingSession)
# ---------------------------------------------------------------------------
class ModEntity(Protocol):
    zone_history: list[dict[str, Any]] | None
    current_zone: str | None
    igt_ms: int
    death_count: int


T = TypeVar("T", bound=ModEntity)


# ---------------------------------------------------------------------------
# BaseHandler
# ---------------------------------------------------------------------------
class BaseHandler(ABC):
    """Shared WebSocket lifecycle: accept, heartbeat, exception handling, cleanup."""

    def __init__(
        self,
        websocket: WebSocket,
        entity_id: object,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        self.websocket = websocket
        self.entity_id = entity_id
        self.session_maker = session_maker
        self.locale = "en"
        self._connected = False
        # Subclasses populate in __init__: msg_type -> async handler(msg)
        self._message_handlers: dict[str, Callable[..., Any]] = {}

    async def run(self) -> None:
        await self.websocket.accept()
        try:
            if not await self._initialize():
                return
            self._connected = True
            heartbeat_task = asyncio.create_task(heartbeat_loop(self.websocket))
            try:
                await self._message_loop()
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        except WebSocketDisconnect:
            logger.info("%s disconnected: %s", type(self).__name__, self.entity_id)
        except Exception:
            logger.exception("%s error: %s", type(self).__name__, self.entity_id)
        finally:
            if self._connected:
                await self._cleanup()

    async def _message_loop(self) -> None:
        rate_limiter = MessageRateLimiter()
        while True:
            raw = await self.websocket.receive_text()
            if not rate_limiter.check():
                logger.warning("Rate limit exceeded: %s", self.entity_id)
                await self.websocket.close(code=4008, reason="Rate limit exceeded")
                return
            try:
                msg = json.loads(raw)
            except (json.JSONDecodeError, ValueError):
                continue
            if msg.get("type") == "pong":
                continue
            await self._handle_message(msg)

    async def _handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        handler = self._message_handlers.get(msg_type)  # type: ignore[arg-type]
        if handler:
            await handler(msg)
        else:
            logger.warning("%s: unknown message type: %s", type(self).__name__, msg_type)

    @abstractmethod
    async def _initialize(self) -> bool: ...

    @abstractmethod
    async def _cleanup(self) -> None: ...


# ---------------------------------------------------------------------------
# BaseModHandler
# ---------------------------------------------------------------------------
class BaseModHandler(BaseHandler, Generic[T]):
    """Mod-specific lifecycle: auth, shared game message handlers.

    Type parameter T is the entity type (Participant or TrainingSession).
    """

    def __init__(
        self,
        websocket: WebSocket,
        entity_id: object,
        session_maker: async_sessionmaker[AsyncSession],
    ) -> None:
        super().__init__(websocket, entity_id, session_maker)
        self._message_handlers = {
            "status_update": self._handle_status_update,
            "event_flag": self._handle_event_flag,
            "zone_query": self._handle_zone_query,
        }

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------
    async def _initialize(self) -> bool:
        if not await self._auth_phase():
            return False
        await self._on_authenticated()
        return True

    async def _cleanup(self) -> None:
        await self._on_disconnect()

    async def _auth_phase(self) -> bool:
        """Run the auth handshake: timeout, JSON parse, type/token check, delegate."""
        try:
            auth_data = await asyncio.wait_for(
                self.websocket.receive_text(), timeout=MOD_AUTH_TIMEOUT
            )
        except TimeoutError:
            logger.warning("Mod auth timeout: %s", self.entity_id)
            await self.websocket.close(code=4001, reason="Auth timeout")
            return False

        try:
            auth_msg = json.loads(auth_data)
        except json.JSONDecodeError:
            await self._send_auth_error("Invalid JSON")
            return False

        if auth_msg.get("type") != "auth" or "mod_token" not in auth_msg:
            await self._send_auth_error("Invalid auth message")
            return False

        return await self._authenticate(auth_msg["mod_token"])

    # ------------------------------------------------------------------
    # Send helpers (use self.websocket, no module-level counterpart)
    # ------------------------------------------------------------------
    async def _send_auth_error(self, message: str) -> None:
        """Send auth error and close connection."""
        logger.warning("Auth error: %s", message)
        try:
            error = AuthErrorMessage(message=message)
            await self.websocket.send_text(error.model_dump_json())
            await self.websocket.close(code=4003, reason=message)
        except Exception:
            pass

    async def _send_error(self, message: str) -> None:
        """Send a generic error message to the mod."""
        try:
            await asyncio.wait_for(
                self.websocket.send_text(ErrorMessage(message=message).model_dump_json()),
                timeout=SEND_TIMEOUT,
            )
        except Exception:
            pass

    async def _send_event_flag_ack(self, message_id: int) -> None:
        """Acknowledge persistence of an event_flag message."""
        try:
            await asyncio.wait_for(
                self.websocket.send_text(
                    EventFlagAckMessage(message_id=message_id).model_dump_json()
                ),
                timeout=SEND_TIMEOUT,
            )
        except Exception:
            pass

    async def _send_zone_query_ack(self, message_id: int) -> None:
        """Acknowledge a zone_query that could not produce a zone_update."""
        try:
            await asyncio.wait_for(
                self.websocket.send_text(
                    ZoneQueryAckMessage(message_id=message_id).model_dump_json()
                ),
                timeout=SEND_TIMEOUT,
            )
        except Exception:
            pass

    async def _send_zone_update(
        self,
        node_id: str,
        graph_json: dict[str, Any],
        zone_history: list[dict[str, Any]] | None,
        *,
        is_first_visit: bool = False,
        message_id: int | None = None,
    ) -> None:
        """Send a zone_update unicast to the originating mod."""
        msg = compute_zone_update(node_id, graph_json, zone_history, is_first_visit=is_first_visit)
        if msg:
            if message_id is not None:
                msg["message_id"] = message_id
            msg = translate_zone_update(msg, self.locale)
            try:
                await asyncio.wait_for(
                    self.websocket.send_text(json.dumps(msg)), timeout=SEND_TIMEOUT
                )
            except Exception:
                logger.warning(
                    "Failed to send zone_update: entity=%s, node=%s",
                    self.entity_id,
                    node_id,
                )

    # ------------------------------------------------------------------
    # Shared game handlers
    # ------------------------------------------------------------------
    async def _handle_status_update(self, msg: dict[str, Any]) -> None:
        """Update IGT and death count. Shared logic for race and training."""
        delta = 0
        history_changed = False
        became_active = False

        async with self.session_maker() as db:
            entity = await self._load_entity_for_status_update(db)
            if entity is None:
                return

            if not await self._validate_for_status_update(entity):
                return

            # Gate: reject stale saves on first initialization
            igt_ms_val = clamp_igt(msg.get("igt_ms"))
            if igt_ms_val is not None and not entity.zone_history and igt_ms_val > MAX_FRESH_IGT_MS:
                logger.warning(
                    "Rejected stale save: %s igt_ms=%d",
                    self.entity_id,
                    igt_ms_val,
                )
                await self._send_error("Please start a New Game")
                return

            if igt_ms_val is not None:
                self._on_igt_change(entity, igt_ms_val)

            # Record start node on first status_update.
            # Must happen BEFORE death attribution so current_zone/zone_history exist.
            if not entity.zone_history:
                graph_json = self._get_graph_json(entity)
                if graph_json:
                    start_node = get_start_node(graph_json)
                    if start_node:
                        entity.zone_history = [
                            {"node_id": start_node, "igt_ms": 0, "type": "spawn"}
                        ]
                        entity.current_zone = start_node
                        history_changed = True
                        became_active = True
                        self._on_first_init(entity, start_node)

            new_death_count = clamp_death_count(msg.get("death_count"))
            if new_death_count is not None:
                delta = new_death_count - entity.death_count
                if delta < 0:
                    logger.warning(
                        "Negative death delta %d for %s (stored=%d, received=%d)",
                        delta,
                        self.entity_id,
                        entity.death_count,
                        new_death_count,
                    )
                if delta > 0 and entity.current_zone and entity.zone_history:
                    new_history = attribute_deaths(
                        entity.zone_history,
                        entity.current_zone,
                        delta,
                    )
                    entity.zone_history = new_history
                    history_changed = True
                entity.death_count = new_death_count

            await db.commit()

        await self._broadcast_after_status_update(
            entity,
            became_active=became_active,
            death_delta=delta,
            history_changed=history_changed,
        )

    async def _handle_event_flag(self, msg: dict[str, Any]) -> None:
        """Handle fog gate traversal or boss kill event flag."""
        flag_id = msg.get("flag_id")
        if not isinstance(flag_id, int):
            return
        raw_message_id = msg.get("message_id")
        message_id = raw_message_id if isinstance(raw_message_id, int) else None

        raw_igt = clamp_igt(msg.get("igt_ms"))
        igt = raw_igt if raw_igt is not None else 0
        is_finish = False
        node_id: str | None = None
        seed_graph: dict[str, Any] | None = None
        is_first_visit = False
        entity: T | None = None

        async with self.session_maker() as db:
            entity = await self._load_entity(db)
            if entity is None:
                return

            if not await self._validate_for_event_flag(entity, message_id):
                return

            # Guard: zone_history must be initialized by the first valid status_update
            # before processing event flags. Without this, stale flags persisted in a
            # loaded save bypass the fresh-save IGT gate in _handle_status_update.
            if not entity.zone_history:
                return

            seed_graph = self._get_graph_json(entity)
            if not seed_graph:
                return

            event_map = seed_graph.get("event_map", {})
            finish_event = seed_graph.get("finish_event")

            # Check finish event first
            if flag_id == finish_event:
                self._on_igt_change(entity, igt)
                await db.commit()
                if message_id is not None:
                    await self._send_event_flag_ack(message_id)
                is_finish = True
                # Exit DB session before calling _handle_finish_event
                # to avoid nested sessions (deadlocks SQLite in tests)
            else:
                # Resolve flag_id to node_id
                node_id = event_map.get(str(flag_id))
                if node_id is None:
                    logger.warning("Unknown event flag %d from %s", flag_id, self.entity_id)
                    return

                old_history = entity.zone_history or []

                # message_id dedup
                if message_id is not None and any(
                    entry.get("type", "fog") == "fog" and entry.get("message_id") == message_id
                    for entry in old_history
                ):
                    await self._send_event_flag_ack(message_id)
                    return

                # Shared entrance dedup
                if is_shared_entrance_duplicate(old_history, node_id, igt):
                    return

                if len(old_history) >= MAX_ZONE_HISTORY:
                    logger.warning("zone_history cap reached for %s", self.entity_id)
                    return

                jump = detect_layer_jump(seed_graph, old_history, node_id)
                if jump is not None:
                    last_nid, last_layer, new_layer, bridges = jump
                    logger.warning(
                        "zone_history layer jump: %s(L%d) -> %s(L%d) "
                        "missing_bridge=%s entity=%s igt=%d message_id=%s",
                        last_nid,
                        last_layer,
                        node_id,
                        new_layer,
                        ",".join(bridges) if bridges else "none",
                        self.entity_id,
                        igt,
                        message_id,
                    )

                is_first_visit = not any(entry.get("node_id") == node_id for entry in old_history)

                self._on_igt_change(entity, igt)
                entity.current_zone = node_id
                new_entry: dict[str, Any] = {"node_id": node_id, "igt_ms": igt, "type": "fog"}
                if message_id is not None:
                    new_entry["message_id"] = message_id
                entity.zone_history = [*old_history, new_entry]

                self._on_zone_entered(entity, node_id, seed_graph, igt)

                await db.commit()
                if message_id is not None:
                    await self._send_event_flag_ack(message_id)

        # Session closed. Safe to open new sessions or broadcast.

        if is_finish:
            await self._handle_finish_event(entity, igt, message_id)
            return

        await self._broadcast_after_event_flag(
            entity, node_id, seed_graph, is_first_visit=is_first_visit
        )

        if node_id and seed_graph:
            await self._send_zone_update(
                node_id,
                seed_graph,
                entity.zone_history,
                is_first_visit=is_first_visit,
            )

    async def _handle_zone_query(self, msg: dict[str, Any]) -> None:
        """Handle zone_query from mod (loading screen exit overlay update)."""
        zq = parse_zone_query_input(msg)
        if zq is None:
            return

        message_id = zq.message_id
        is_first_visit = False
        history_changed = False
        node_id: str | None = None
        graph_json: dict[str, Any] | None = None

        async with self.session_maker() as db:
            entity = await self._load_entity(db)
            if entity is None:
                if message_id is not None:
                    await self._send_zone_query_ack(message_id)
                return

            if not await self._validate_for_zone_query(entity, message_id):
                return

            # Guard: same as _handle_event_flag, require zone_history initialization
            if not entity.zone_history:
                if message_id is not None:
                    await self._send_zone_query_ack(message_id)
                return

            graph_json = self._get_graph_json(entity)
            if not graph_json:
                if message_id is not None:
                    await self._send_zone_query_ack(message_id)
                return

            node_id = resolve_zone_query(
                graph_json,
                get_graces_mapping(),
                grace_entity_id=zq.grace_entity_id,
                map_id=zq.map_id,
                position=zq.position,
                play_region_id=zq.play_region_id,
                zone_history=entity.zone_history,
            )
            if node_id is None:
                logger.debug(
                    "zone_query: unresolved (grace=%s, map=%s) for %s",
                    zq.grace_entity_id,
                    zq.map_id,
                    self.entity_id,
                )
                if message_id is not None:
                    await self._send_zone_query_ack(message_id)
                return

            # Fast travel (Strategy 1 grace lookup) bypasses the history filter,
            # so it can resolve to a node that has never been traversed via fog.
            # That is normally impossible in fog rando (unreachable graces are
            # not in the menu) and points at a grace mapping bug or an
            # unexpected warp, so warn for observability. parse_zone_query_input
            # has already replaced a 0 grace_entity_id with None.
            if zq.grace_entity_id is not None and not any(
                entry.get("node_id") == node_id for entry in entity.zone_history or []
            ):
                logger.warning(
                    "zone_query resolved to unvisited node via grace: "
                    "node=%s grace_entity_id=%s entity=%s message_id=%s",
                    node_id,
                    zq.grace_entity_id,
                    self.entity_id,
                    message_id,
                )

            # Record backtrack entry when the player moved to a different node
            # (death/teleport/quit-out, no event flag fired)
            if node_id != entity.current_zone:
                logger.info(
                    "zone_query backtrack: %s -> %s for %s",
                    entity.current_zone,
                    node_id,
                    self.entity_id,
                )
                igt = zq.igt_ms if zq.igt_ms is not None else entity.igt_ms
                old_history = entity.zone_history or []

                if message_id is not None and any(
                    entry.get("type") == "backtrack" and entry.get("message_id") == message_id
                    for entry in old_history
                ):
                    pass  # Dedup: already persisted, skip to zone_update
                elif len(old_history) >= MAX_ZONE_HISTORY:
                    logger.warning("zone_history cap reached for %s", self.entity_id)
                else:
                    is_first_visit = not any(
                        entry.get("node_id") == node_id for entry in old_history
                    )
                    self._on_igt_change(entity, igt)
                    new_entry: dict[str, Any] = {
                        "node_id": node_id,
                        "igt_ms": igt,
                        "type": "backtrack",
                    }
                    if message_id is not None:
                        new_entry["message_id"] = message_id
                    entity.zone_history = [
                        *old_history,
                        new_entry,
                    ]
                    history_changed = True

                self._on_zone_entered(entity, node_id, graph_json, igt)

            entity.current_zone = node_id
            await db.commit()

        # Unicast zone_update to originating mod
        if node_id and graph_json:
            await self._send_zone_update(
                node_id,
                graph_json,
                entity.zone_history,
                is_first_visit=is_first_visit,
                message_id=message_id,
            )

        await self._broadcast_after_zone_query(
            entity, is_first_visit=is_first_visit, history_changed=history_changed
        )

    # ------------------------------------------------------------------
    # Abstract methods (must be implemented by subclasses)
    # ------------------------------------------------------------------
    @abstractmethod
    async def _authenticate(self, mod_token: str) -> bool: ...

    @abstractmethod
    async def _on_authenticated(self) -> None: ...

    @abstractmethod
    async def _on_disconnect(self) -> None: ...

    @abstractmethod
    async def _load_entity(self, db: AsyncSession) -> T | None: ...

    @abstractmethod
    async def _load_entity_for_status_update(self, db: AsyncSession) -> T | None: ...

    @abstractmethod
    def _get_graph_json(self, entity: T) -> dict[str, Any] | None: ...

    @abstractmethod
    async def _validate_for_status_update(self, entity: T) -> bool: ...

    @abstractmethod
    async def _validate_for_event_flag(self, entity: T, message_id: int | None) -> bool: ...

    @abstractmethod
    async def _validate_for_zone_query(self, entity: T, message_id: int | None) -> bool: ...

    @abstractmethod
    async def _handle_finish_event(
        self,
        entity: T,
        igt: int,
        message_id: int | None,
    ) -> None: ...

    @abstractmethod
    async def _broadcast_after_status_update(
        self,
        entity: T,
        *,
        became_active: bool,
        death_delta: int,
        history_changed: bool,
    ) -> None: ...

    @abstractmethod
    async def _broadcast_after_event_flag(
        self,
        entity: T,
        node_id: str | None,
        seed_graph: dict[str, Any] | None,
        *,
        is_first_visit: bool,
    ) -> None: ...

    @abstractmethod
    async def _broadcast_after_zone_query(
        self,
        entity: T,
        *,
        is_first_visit: bool,
        history_changed: bool,
    ) -> None: ...

    # ------------------------------------------------------------------
    # Virtual methods (with defaults, overridable by subclasses)
    # ------------------------------------------------------------------
    def _on_igt_change(self, entity: T, igt_ms: int) -> None:
        """Update entity IGT. Override to also set last_igt_change_at (race)."""
        entity.igt_ms = igt_ms

    def _on_zone_entered(
        self, entity: T, node_id: str, graph_json: dict[str, Any], igt: int
    ) -> None:
        """Hook called when a zone is entered. Override for layer tracking (race)."""

    def _on_first_init(self, entity: T, start_node: str) -> None:
        """Hook called on first zone initialization. Override for READY->PLAYING (race)."""


# ---------------------------------------------------------------------------
# BaseSpectatorHandler
# ---------------------------------------------------------------------------
class BaseSpectatorHandler(BaseHandler):
    """Shared spectator lifecycle: optional auth, initial state."""

    async def _initialize(self) -> bool:
        self.locale = self.websocket.query_params.get("locale", "en")
        if not await self._auth_and_setup():
            return False
        await self._register()
        return True

    async def _cleanup(self) -> None:
        await self._unregister()

    # _message_loop, _handle_message, _message_handlers inherited from BaseHandler.
    # Subclasses add entries to _message_handlers in __init__.

    @abstractmethod
    async def _auth_and_setup(self) -> bool: ...

    @abstractmethod
    async def _register(self) -> None: ...

    @abstractmethod
    async def _unregister(self) -> None: ...
