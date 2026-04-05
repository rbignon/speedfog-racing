"""WebSocket connection manager for race rooms."""

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from fastapi import WebSocket

from speedfog_racing.models import Participant
from speedfog_racing.services.layer_service import get_layer_for_node, get_tier_for_node
from speedfog_racing.services.twitch_live import twitch_live_service
from speedfog_racing.websocket.schemas import (
    LeaderboardUpdateMessage,
    ParticipantInfo,
    PlayerUpdateMessage,
    RaceStatusChangeMessage,
    SpectatorCountMessage,
    ZoneHistoryMessage,
)

logger = logging.getLogger(__name__)

SEND_TIMEOUT = 5.0  # seconds before a send is considered failed


@dataclass
class ModConnection:
    """A connected mod client."""

    websocket: WebSocket
    participant_id: uuid.UUID
    user_id: uuid.UUID
    locale: str = "en"


@dataclass
class SpectatorConnection:
    """A connected spectator client."""

    websocket: WebSocket
    user_id: uuid.UUID | None = None
    locale: str = "en"
    role: str | None = None  # "organizer" | "admin" | "caster" | "participant"
    participant_id: uuid.UUID | None = None
    is_playing: bool = False  # True if participant currently in PLAYING status during RUNNING
    # Unique id for O(1) removal from RaceRoom.spectators dict.
    connection_id: uuid.UUID = field(default_factory=uuid.uuid4)


@dataclass
class RaceRoom:
    """A room for a specific race with mod and spectator connections."""

    race_id: uuid.UUID
    # participant_id -> connection
    mods: dict[uuid.UUID, ModConnection] = field(default_factory=dict)
    # connection_id -> connection (dict for O(1) add/remove during broadcasts)
    spectators: dict[uuid.UUID, SpectatorConnection] = field(default_factory=dict)

    async def broadcast_to_mods(self, message: str) -> None:
        """Send message to all connected mods concurrently with timeout."""
        if not self.mods:
            return

        # Snapshot to avoid issues with concurrent dict modification
        snapshot = dict(self.mods)

        async def _send(participant_id: uuid.UUID, conn: ModConnection) -> uuid.UUID | None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                logger.debug(
                    "Mod broadcast failed, removing: race=%s, participant=%s",
                    self.race_id,
                    participant_id,
                )
                return participant_id
            return None

        results = await asyncio.gather(*(_send(pid, conn) for pid, conn in snapshot.items()))
        for pid in results:
            if pid is not None:
                self.mods.pop(pid, None)

    async def broadcast_to_spectators(self, message: str) -> None:
        """Send message to all connected spectators concurrently with timeout."""
        if not self.spectators:
            return

        # Snapshot to avoid issues with concurrent dict modification.
        # During the gather, connect_spectator/disconnect_spectator can
        # modify self.spectators.
        snapshot = list(self.spectators.values())

        async def _send(conn: SpectatorConnection) -> SpectatorConnection | None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                logger.debug("Spectator broadcast failed, removing: race=%s", self.race_id)
                return conn
            return None

        results = await asyncio.gather(*(_send(c) for c in snapshot))
        for conn in results:
            if conn is not None:
                self.spectators.pop(conn.connection_id, None)

    async def broadcast_to_all(self, message: str) -> None:
        """Send message to all connections (mods + spectators) concurrently."""
        await asyncio.gather(
            self.broadcast_to_mods(message),
            self.broadcast_to_spectators(message),
        )

    async def broadcast_chat_participants(self, message: str) -> None:
        """Broadcast to spectator connections with a race role (participant/organizer/caster/admin).

        Only sends to connections where role is not None.
        """
        snapshot = [c for c in self.spectators.values() if c.role is not None]
        if not snapshot:
            return
        failed: list[SpectatorConnection] = []

        async def _send(conn: SpectatorConnection) -> None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                failed.append(conn)

        await asyncio.gather(*(_send(c) for c in snapshot))
        for conn in failed:
            self.spectators.pop(conn.connection_id, None)

    async def broadcast_chat_public(self, message: str) -> None:
        """Broadcast to authenticated spectators, excluding playing participants."""
        snapshot = [
            c for c in self.spectators.values() if c.user_id is not None and not c.is_playing
        ]
        if not snapshot:
            return
        failed: list[SpectatorConnection] = []

        async def _send(conn: SpectatorConnection) -> None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                failed.append(conn)

        await asyncio.gather(*(_send(c) for c in snapshot))
        for conn in failed:
            self.spectators.pop(conn.connection_id, None)

    def get_spectator_by_user_id(self, user_id: uuid.UUID) -> SpectatorConnection | None:
        """Find a spectator connection by user ID."""
        for conn in self.spectators.values():
            if conn.user_id == user_id:
                return conn
        return None

    def mark_participants_playing(self) -> None:
        """Set is_playing=True on all participant spectator connections."""
        for conn in self.spectators.values():
            if conn.role == "participant":
                conn.is_playing = True

    def clear_is_playing(self, user_id: uuid.UUID) -> None:
        """Clear is_playing for a specific user's spectator connection."""
        conn = self.get_spectator_by_user_id(user_id)
        if conn:
            conn.is_playing = False

    def clear_all_playing(self) -> None:
        """Clear is_playing on all spectator connections."""
        for conn in self.spectators.values():
            conn.is_playing = False


class ConnectionManager:
    """Manages all WebSocket connections across races."""

    def __init__(self) -> None:
        self.rooms: dict[uuid.UUID, RaceRoom] = {}

    def get_or_create_room(self, race_id: uuid.UUID) -> RaceRoom:
        """Get or create a room for a race."""
        if race_id not in self.rooms:
            self.rooms[race_id] = RaceRoom(race_id=race_id)
        return self.rooms[race_id]

    def get_room(self, race_id: uuid.UUID) -> RaceRoom | None:
        """Get a room if it exists."""
        return self.rooms.get(race_id)

    async def connect_mod(
        self,
        race_id: uuid.UUID,
        participant_id: uuid.UUID,
        user_id: uuid.UUID,
        websocket: WebSocket,
        locale: str = "en",
    ) -> None:
        """Register a mod connection, replacing any existing one for this participant.

        If a previous connection exists (likely a ghost after a network drop),
        it is closed with code 4000 so the old handler's receive loop exits.
        """
        room = self.get_or_create_room(race_id)
        existing = room.mods.get(participant_id)
        room.mods[participant_id] = ModConnection(
            websocket=websocket,
            participant_id=participant_id,
            user_id=user_id,
            locale=locale,
        )
        if existing is not None:
            logger.info(f"Mod replaced: race={race_id}, participant={participant_id}")
            try:
                await existing.websocket.close(code=4000, reason="replaced by new connection")
            except Exception:
                logger.debug(
                    "Failed to close replaced mod connection: race=%s, participant=%s",
                    race_id,
                    participant_id,
                )
        else:
            logger.info(f"Mod connected: race={race_id}, participant={participant_id}")

    async def disconnect_mod(
        self,
        race_id: uuid.UUID,
        participant_id: uuid.UUID,
        websocket: WebSocket | None = None,
    ) -> None:
        """Remove a mod connection.

        If ``websocket`` is provided, only removes the entry when it still
        refers to that websocket. This prevents an old handler from
        inadvertently removing a newer connection that has replaced it.
        """
        room = self.get_room(race_id)
        if not room:
            return
        current = room.mods.get(participant_id)
        if current is None:
            return
        if websocket is not None and current.websocket is not websocket:
            logger.debug(
                "Stale mod disconnect ignored: race=%s, participant=%s",
                race_id,
                participant_id,
            )
            return
        room.mods.pop(participant_id, None)
        logger.info(f"Mod disconnected: race={race_id}, participant={participant_id}")
        if not room.mods and not room.spectators:
            self.rooms.pop(race_id, None)

    async def connect_spectator(self, race_id: uuid.UUID, conn: SpectatorConnection) -> None:
        """Register a spectator connection."""
        room = self.get_or_create_room(race_id)
        room.spectators[conn.connection_id] = conn
        logger.info(f"Spectator connected: race={race_id}")
        await self._broadcast_spectator_count(room)

    async def disconnect_spectator(self, race_id: uuid.UUID, conn: SpectatorConnection) -> None:
        """Remove a spectator connection."""
        room = self.get_room(race_id)
        if room:
            room.spectators.pop(conn.connection_id, None)
            logger.info(f"Spectator disconnected: race={race_id}")
            await self._broadcast_spectator_count(room)
            if not room.mods and not room.spectators:
                self.rooms.pop(race_id, None)

    async def close_room(self, race_id: uuid.UUID, code: int = 1000, reason: str = "") -> None:
        """Close all WebSocket connections in a room and remove it."""
        room = self.rooms.pop(race_id, None)
        if not room:
            return

        for mod_conn in room.mods.values():
            try:
                await mod_conn.websocket.close(code=code, reason=reason)
            except Exception:
                logger.debug("Failed to close mod connection in room %s", race_id)

        for spec_conn in room.spectators.values():
            try:
                await spec_conn.websocket.close(code=code, reason=reason)
            except Exception:
                logger.debug("Failed to close spectator connection in room %s", race_id)

        logger.info(f"Closed room: race={race_id}")

    def is_mod_connected(self, race_id: uuid.UUID, participant_id: uuid.UUID) -> bool:
        """Check if a mod is connected."""
        room = self.get_room(race_id)
        return room is not None and participant_id in room.mods

    async def broadcast_leaderboard(
        self,
        race_id: uuid.UUID,
        participants: list[Participant],
        *,
        graph_json: dict[str, Any] | None = None,
    ) -> None:
        """Broadcast leaderboard update to all connections in a room."""
        room = self.get_room(race_id)
        if not room:
            return

        sorted_participants, entry_igts = sort_leaderboard(participants, graph_json=graph_json)
        connected_ids = set(room.mods.keys())

        # Compute leader splits for gap timing
        leader_splits: dict[int, int] = {}
        leader_igt_ms = 0
        has_leader = False
        if graph_json and sorted_participants:
            leader = sorted_participants[0]
            if leader.status.value in ("playing", "finished"):
                has_leader = True
                leader_igt_ms = leader.igt_ms
                leader_splits = build_leader_splits(leader.zone_history, graph_json)

        participant_infos = [
            participant_to_info(
                p,
                connected_ids=connected_ids,
                graph_json=graph_json,
                gap_ms=compute_gap_ms(
                    p.status.value,
                    igt_ms=p.igt_ms,
                    current_layer=p.current_layer,
                    player_layer_entry_igt=entry_igts.get(p.id),
                    leader_splits=leader_splits,
                    leader_igt_ms=leader_igt_ms,
                    is_leader=(has_leader and i == 0),
                    leader_finished=(
                        has_leader and sorted_participants[0].status.value == "finished"
                    ),
                )
                if has_leader and graph_json
                else None,
                layer_entry_igt=entry_igts.get(p.id) if graph_json else None,
            )
            for i, p in enumerate(sorted_participants)
        ]

        message = LeaderboardUpdateMessage(
            participants=participant_infos,
            leader_splits=leader_splits if leader_splits else None,
        )
        await room.broadcast_to_all(message.model_dump_json())

    async def broadcast_player_update(
        self,
        race_id: uuid.UUID,
        participant: Participant,
        *,
        graph_json: dict[str, Any] | None = None,
    ) -> None:
        """Broadcast a single player update to all connections (mods + spectators).

        Note: gap_ms is not included here because computing it requires the full
        sorted participants list (for leader context). Clients receive gap data
        via leaderboard_update messages instead; mods recompute gaps client-side.
        """
        room = self.get_room(race_id)
        if not room:
            return

        connected_ids = set(room.mods.keys())
        message = PlayerUpdateMessage(
            player=participant_to_info(
                participant,
                connected_ids=connected_ids,
                graph_json=graph_json,
                layer_entry_igt=get_layer_entry_igt(
                    participant.zone_history, participant.current_layer, graph_json
                )
                if graph_json
                else None,
            )
        )
        await room.broadcast_to_all(message.model_dump_json())

    async def _broadcast_spectator_count(self, room: RaceRoom) -> None:
        """Broadcast spectator count to all spectators in a room."""
        msg = SpectatorCountMessage(count=len(room.spectators))
        await room.broadcast_to_spectators(msg.model_dump_json())

    async def broadcast_race_status(
        self,
        race_id: uuid.UUID,
        status: str,
        started_at: str | None = None,
        countdown_seconds: int | None = None,
    ) -> None:
        """Broadcast race status change to all connections."""
        room = self.get_room(race_id)
        if not room:
            return

        message = RaceStatusChangeMessage(
            status=status, started_at=started_at, countdown_seconds=countdown_seconds
        )
        await room.broadcast_to_all(message.model_dump_json())

    async def broadcast_zone_history(
        self,
        race_id: uuid.UUID,
        participant_id: uuid.UUID,
        history: list[dict[str, Any]],
    ) -> None:
        """Broadcast a full zone_history snapshot for a single participant.

        Sent on new-zone appends AND on death-attribution updates. The
        full list is transmitted each time so clients can self-heal from
        any missed message. Spectators only: mods do not consume
        zone_history.
        """
        room = self.get_room(race_id)
        if not room:
            return

        message = ZoneHistoryMessage(
            participant_id=str(participant_id),
            history=history,
        )
        await room.broadcast_to_spectators(message.model_dump_json())


def build_leader_splits(
    zone_history: list[dict[str, Any]] | None,
    graph_json: dict[str, Any],
) -> dict[int, int]:
    """Build a map of layer -> first IGT at that layer from zone_history."""
    if not zone_history:
        return {}
    nodes = graph_json.get("nodes", {})
    splits: dict[int, int] = {}
    for entry in zone_history:
        node_id = entry.get("node_id")
        igt = entry.get("igt_ms")
        if node_id is None or igt is None:
            continue
        # Skip unknown nodes: get_layer_for_node defaults to 0 which would
        # produce a bogus split for layer 0.
        if str(node_id) not in nodes:
            continue
        layer = get_layer_for_node(str(node_id), graph_json)
        if layer not in splits:
            splits[layer] = int(igt)
    return splits


def get_layer_entry_igt(
    zone_history: list[dict[str, Any]] | None,
    current_layer: int,
    graph_json: dict[str, Any],
) -> int | None:
    """Get the player's IGT when they first entered their current layer."""
    if not zone_history:
        return None
    nodes = graph_json.get("nodes", {})
    for entry in zone_history:
        node_id = entry.get("node_id")
        igt = entry.get("igt_ms")
        if node_id is None or igt is None:
            continue
        if str(node_id) not in nodes:
            continue
        layer = get_layer_for_node(str(node_id), graph_json)
        if layer == current_layer:
            return int(igt)
    return None


def compute_gap_ms(
    status: str,
    *,
    igt_ms: int,
    current_layer: int,
    player_layer_entry_igt: int | None,
    leader_splits: dict[int, int],
    leader_igt_ms: int,
    is_leader: bool = False,
    leader_finished: bool = False,
) -> int | None:
    """Compute gap_ms for a participant relative to the leader (LiveSplit-style).

    - While player's IGT is within leader's time budget on the layer: gap = entry delta
    - Once player exceeds leader's exit IGT: gap = entry delta + overshoot
    - On the last layer after leader finishes: use leader's finish IGT as exit time
    """
    if is_leader:
        return None
    if status not in ("playing", "finished"):
        return None
    if status == "finished":
        return igt_ms - leader_igt_ms
    # Playing: LiveSplit-style split comparison
    leader_entry = leader_splits.get(current_layer)
    if leader_entry is None or player_layer_entry_igt is None:
        return None
    entry_delta = player_layer_entry_igt - leader_entry
    # Leader's exit = leader's entry on next layer
    leader_exit = leader_splits.get(current_layer + 1)
    if leader_exit is None:
        if leader_finished:
            # Last layer: leader finished, use finish IGT as exit time
            leader_exit = leader_igt_ms
        else:
            # Leader hasn't left this layer yet, show entry delta only
            return entry_delta
    # Compare time spent in layer, not absolute IGTs
    time_in_layer = igt_ms - player_layer_entry_igt
    leader_time_in_layer = leader_exit - leader_entry
    if time_in_layer <= leader_time_in_layer:
        # Within leader's time budget, fixed entry delta
        return entry_delta
    # Exceeded leader's time budget: entry delay + layer overshoot
    return entry_delta + (time_in_layer - leader_time_in_layer)


def participant_to_info(
    participant: Participant,
    *,
    connected_ids: set[uuid.UUID] | None = None,
    graph_json: dict[str, Any] | None = None,
    gap_ms: int | None = None,
    layer_entry_igt: int | None = None,
    include_zone_history: bool = False,
) -> ParticipantInfo:
    """Convert a Participant model to ParticipantInfo schema.

    zone_history is omitted by default (saves ~50 KB per broadcast with
    10 participants). Callers sending the initial race state to a
    spectator should pass include_zone_history=True; high-frequency
    broadcasts (leaderboard_update, player_update) rely on
    ZoneHistoryMessage snapshots instead.
    """
    # Compute tier on the fly from current_zone + graph_json
    tier: int | None = None
    if graph_json and participant.current_zone:
        tier = get_tier_for_node(participant.current_zone, graph_json)

    return ParticipantInfo(
        id=str(participant.id),
        twitch_username=participant.user.twitch_username,
        twitch_display_name=participant.user.twitch_display_name,
        status=participant.status.value,
        current_zone=participant.current_zone,
        current_layer=participant.current_layer,
        current_layer_tier=tier,
        igt_ms=participant.igt_ms,
        death_count=participant.death_count,
        color_index=participant.color_index,
        mod_connected=participant.id in connected_ids if connected_ids else False,
        zone_history=participant.zone_history if include_zone_history else None,
        gap_ms=gap_ms,
        layer_entry_igt=layer_entry_igt,
        is_live=twitch_live_service.is_live(participant.user.twitch_username),
        stream_url=twitch_live_service.stream_url(participant.user.twitch_username),
    )


def sort_leaderboard(
    participants: list[Participant],
    *,
    graph_json: dict[str, Any] | None = None,
) -> tuple[list[Participant], dict[uuid.UUID, int | None]]:
    """Sort participants for leaderboard display.

    Returns (sorted_participants, entry_igts) where entry_igts maps each
    participant ID to their layer entry IGT (None if unavailable).
    The caller can reuse entry_igts instead of recomputing it.

    Priority:
    1. Finished players first, sorted by IGT (lowest first)
    2. Playing players by layer (highest first), then layer entry IGT (lowest first)
    3. Ready players
    4. Registered players
    5. Abandoned (DNF) players last, sorted by layer (highest first), then IGT (lowest first)
    """
    status_priority = {
        "finished": 0,
        "playing": 1,
        "ready": 2,
        "registered": 3,
        "abandoned": 4,
    }

    # Pre-compute layer entry IGTs for all participants (shared with caller)
    entry_igts: dict[uuid.UUID, int | None] = {}
    if graph_json:
        for p in participants:
            entry_igts[p.id] = get_layer_entry_igt(p.zone_history, p.current_layer, graph_json)

    def sort_key(p: Participant) -> tuple[int, int, int]:
        status = p.status.value
        priority = status_priority.get(status, 99)

        if status == "finished":
            return (priority, p.igt_ms, 0)
        elif status == "playing":
            raw = entry_igts.get(p.id)
            entry_igt = raw if raw is not None else p.igt_ms
            return (priority, -p.current_layer, entry_igt)
        elif status == "abandoned":
            return (priority, -p.current_layer, p.igt_ms)
        else:
            return (priority, 0, 0)

    return sorted(participants, key=sort_key), entry_igts


# Global connection manager instance
manager = ConnectionManager()
