"""WebSocket connection manager for race rooms."""

import asyncio
import logging
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from typing import Any

from fastapi import WebSocket

from speedfog_racing.models import Participant, ParticipantStatus, Race
from speedfog_racing.rewards.catalog import DEFAULT_TEMPLATE_ID, NAME_TEMPLATES
from speedfog_racing.services.chat_access import (
    can_read_participants_chat,
    can_read_public_chat,
)
from speedfog_racing.services.layer_service import get_layer_for_node, get_tier_for_node
from speedfog_racing.services.twitch_live import twitch_live_service
from speedfog_racing.websocket.race.projection import (
    ProjectedParticipant,
    project_participant_at,
)
from speedfog_racing.websocket.schemas import (
    DailyStreakUpdateMessage,
    LeaderboardUpdateMessage,
    NameTemplatePayload,
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
    # Cached participant status, used by chat_access helpers to evaluate
    # public-chat access without iterating race.participants per broadcast.
    # ``None`` for non-participants. Populated at auth and refreshed when
    # the participant transitions (race start, finish, abandon).
    participant_status: ParticipantStatus | None = None
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

    async def send_to_mod(self, participant_id: uuid.UUID, message: str) -> bool:
        """Unicast a message to a single mod connection.

        Returns True if the message was sent; False if the mod was not
        connected or the send failed (in which case the connection is
        evicted from the room).
        """
        conn = self.mods.get(participant_id)
        if conn is None:
            return False
        try:
            await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            return True
        except Exception:
            logger.debug(
                "Mod unicast failed, removing: race=%s, participant=%s",
                self.race_id,
                participant_id,
            )
            self.mods.pop(participant_id, None)
            return False

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
        """Broadcast to spectator connections with a race role.

        Routed through ``can_read_participants_chat`` so the filter stays
        in lockstep with the helpers used at history load and send.
        """
        snapshot = [c for c in self.spectators.values() if can_read_participants_chat(role=c.role)]
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

    async def broadcast_chat_public(self, message: str, race: Race) -> None:
        """Broadcast public chat respecting per-connection access.

        ``race`` is the current race row (used for status and the late-join
        deadline). Caller is responsible for passing a fresh-enough race;
        for the public-chat use case, status and ``started_at`` change
        infrequently (race start, finish), so callers that already hold a
        loaded race object can pass it directly.
        """
        now = datetime.now(UTC)
        snapshot = [
            c
            for c in self.spectators.values()
            if can_read_public_chat(
                race,
                role=c.role,
                participant_status=c.participant_status,
                now=now,
            )
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
        """Set participant_status to PLAYING on every participant connection."""
        for conn in self.spectators.values():
            if conn.role == "participant":
                conn.participant_status = ParticipantStatus.PLAYING

    def set_participant_status(self, user_id: uuid.UUID, status: ParticipantStatus) -> None:
        """Update the cached participant status for every connection of a user.

        Multi-tab users have multiple spectator connections sharing the
        same user_id, all of which need to see the transition.
        """
        for conn in self.spectators.values():
            if conn.user_id == user_id:
                conn.participant_status = status


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
        daily_date: date | None = None,
    ) -> None:
        """Broadcast leaderboard update to all connections in a room.

        For non-daily races (``daily_date is None``) every connection
        receives the same real-state payload. For daily races, web
        spectators still receive the real payload, but each connected
        mod receives a payload tailored to its viewer state: the real
        payload when the viewer is not currently playing, otherwise a
        projected payload built from each ghost's state at the viewer's
        IGT (see ``projection.project_participant_at``).
        """
        room = self.get_room(race_id)
        if not room:
            return

        sorted_participants, entry_igts = sort_leaderboard(participants, graph_json=graph_json)
        connected_ids = set(room.mods.keys())

        leader_splits, leader_igt_ms, has_leader = _build_leader_context(
            sorted_participants, graph_json
        )

        real_payload = _build_leaderboard_payload(
            sorted_participants,
            entry_igts,
            connected_ids=connected_ids,
            graph_json=graph_json,
            leader_splits=leader_splits,
            leader_igt_ms=leader_igt_ms,
            has_leader=has_leader,
        )

        if daily_date is None:
            await room.broadcast_to_all(real_payload)
            return

        # Daily race: spectators see real state; each mod gets its own view.
        by_id = {p.id: p for p in participants}

        async def _send_to_mod(participant_id: uuid.UUID) -> None:
            viewer = by_id.get(participant_id)
            if viewer is None or viewer.status != ParticipantStatus.PLAYING:
                await room.send_to_mod(participant_id, real_payload)
                return
            projected_payload = _build_projected_payload_for_viewer(
                viewer=viewer,
                participants=participants,
                connected_ids=connected_ids,
                graph_json=graph_json,
            )
            await room.send_to_mod(participant_id, projected_payload)

        await asyncio.gather(
            room.broadcast_to_spectators(real_payload),
            *(_send_to_mod(pid) for pid in list(room.mods.keys())),
        )

    async def send_projected_to_mod(
        self,
        *,
        race_id: uuid.UUID,
        participant_id: uuid.UUID,
        participants: list[Participant],
        graph_json: dict[str, Any] | None,
    ) -> None:
        """Unicast a projected leaderboard to a single mod (daily races).

        No-op when the viewer is not connected or not currently playing.
        """
        room = self.get_room(race_id)
        if not room:
            return
        viewer = next((p for p in participants if p.id == participant_id), None)
        if viewer is None or viewer.status != ParticipantStatus.PLAYING:
            return
        connected_ids = set(room.mods.keys())
        payload = _build_projected_payload_for_viewer(
            viewer=viewer,
            participants=participants,
            connected_ids=connected_ids,
            graph_json=graph_json,
        )
        await room.send_to_mod(participant_id, payload)

    async def send_daily_streak_update_to_user(
        self,
        race_id: uuid.UUID,
        user_id: uuid.UUID,
        *,
        current: int,
        best: int,
        freeze_count: int,
        freeze_consumed_for: date | None = None,
    ) -> None:
        """Unicast ``daily_streak_update`` to every connection of ``user_id`` on
        this race room (mod + all spectator connections matching the user).

        ``freeze_consumed_for`` is forwarded as-is; see
        ``DailyStreakUpdateMessage`` for the contract.

        No-op when the user has no open connections.
        """
        room = self.get_room(race_id)
        if room is None:
            return
        payload = DailyStreakUpdateMessage(
            current=current,
            best=best,
            freeze_count=freeze_count,
            freeze_consumed_for=freeze_consumed_for,
        ).model_dump_json()

        mod_conn = next(
            (conn for conn in room.mods.values() if conn.user_id == user_id),
            None,
        )
        spectator_conns = [conn for conn in room.spectators.values() if conn.user_id == user_id]
        if mod_conn is None and not spectator_conns:
            return

        failed_mod: uuid.UUID | None = None
        failed_spectators: list[SpectatorConnection] = []

        async def _send_mod() -> None:
            nonlocal failed_mod
            if mod_conn is None:
                return
            try:
                await asyncio.wait_for(mod_conn.websocket.send_text(payload), timeout=SEND_TIMEOUT)
            except Exception:
                failed_mod = mod_conn.participant_id

        async def _send_spectator(conn: SpectatorConnection) -> None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(payload), timeout=SEND_TIMEOUT)
            except Exception:
                failed_spectators.append(conn)

        await asyncio.gather(
            _send_mod(),
            *(_send_spectator(c) for c in spectator_conns),
        )

        if failed_mod is not None:
            room.mods.pop(failed_mod, None)
        for conn in failed_spectators:
            room.spectators.pop(conn.connection_id, None)

    async def broadcast_player_update(
        self,
        race_id: uuid.UUID,
        participant: Participant,
        *,
        graph_json: dict[str, Any] | None = None,
        daily_date: date | None = None,
    ) -> None:
        """Broadcast a single player update.

        Note: gap_ms is not included here because computing it requires the full
        sorted participants list (for leader context). Clients receive gap data
        via leaderboard_update messages instead; mods recompute gaps client-side.

        On daily races, routed to spectators only: mods overwrite the matching
        row from any player_update, which would desync the projected leaderboard.
        """
        room = self.get_room(race_id)
        if not room:
            return
        if daily_date is not None and not room.spectators:
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
        payload = message.model_dump_json()
        if daily_date is not None:
            await room.broadcast_to_spectators(payload)
        else:
            await room.broadcast_to_all(payload)

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
    participant: Participant | ProjectedParticipant,
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

    # The default template is a sentinel for "no override": the mod and web
    # render the name in its status color (preserving functional readability).
    # We only emit name_template when the user has explicitly equipped a
    # non-default one.
    equipped_template_id = participant.user.equipped_name_template_id
    name_template_payload: NameTemplatePayload | None = None
    if equipped_template_id is not None and equipped_template_id != DEFAULT_TEMPLATE_ID:
        template = NAME_TEMPLATES.get(equipped_template_id)
        if template is not None:
            name_template_payload = NameTemplatePayload(
                color=template.color,
                gradient=list(template.gradient) if template.gradient is not None else None,
            )

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
        equipped_badge_id=participant.user.equipped_badge_id,
        equipped_name_template_id=participant.user.equipped_name_template_id,
        name_template=name_template_payload,
    )


def sort_leaderboard(
    participants: Sequence[Participant | ProjectedParticipant],
    *,
    graph_json: dict[str, Any] | None = None,
) -> tuple[list[Participant | ProjectedParticipant], dict[uuid.UUID, int | None]]:
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

    # Pre-compute layer entry IGTs for all participants (shared with caller).
    # Fast path: read the per-participant cache populated at layer advance.
    # Fallback: scan zone_history via get_layer_entry_igt for rows migrated
    # before the cache existed (or when the cache misses for any reason).
    entry_igts: dict[uuid.UUID, int | None] = {}
    if graph_json:
        for p in participants:
            key = str(p.current_layer)
            cached = (p.layer_entry_igts or {}).get(key)
            if cached is not None:
                entry_igts[p.id] = cached
            else:
                entry_igts[p.id] = get_layer_entry_igt(p.zone_history, p.current_layer, graph_json)

    def sort_key(p: Participant | ProjectedParticipant) -> tuple[int, int, int]:
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


def _build_leader_context(
    sorted_participants: Sequence[Participant | ProjectedParticipant],
    graph_json: dict[str, Any] | None,
) -> tuple[dict[int, int], int, bool]:
    """Compute leader splits + leader IGT for gap timing.

    Shared by the real-state and projected payload builders so both
    branches surface gap_ms relative to the same leader semantics.
    """
    leader_splits: dict[int, int] = {}
    leader_igt_ms = 0
    has_leader = False
    if graph_json and sorted_participants:
        leader = sorted_participants[0]
        if leader.status in (ParticipantStatus.PLAYING, ParticipantStatus.FINISHED):
            has_leader = True
            leader_igt_ms = leader.igt_ms
            leader_splits = build_leader_splits(leader.zone_history, graph_json)
    return leader_splits, leader_igt_ms, has_leader


def _build_leaderboard_payload(
    sorted_participants: Sequence[Participant | ProjectedParticipant],
    entry_igts: dict[uuid.UUID, int | None],
    *,
    connected_ids: set[uuid.UUID],
    graph_json: dict[str, Any] | None,
    leader_splits: dict[int, int],
    leader_igt_ms: int,
    has_leader: bool,
) -> str:
    """Serialize a LeaderboardUpdateMessage from already-sorted participants."""
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
                    has_leader and sorted_participants[0].status == ParticipantStatus.FINISHED
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
    return message.model_dump_json()


def _build_projected_payload_for_viewer(
    *,
    viewer: Participant,
    participants: list[Participant],
    connected_ids: set[uuid.UUID],
    graph_json: dict[str, Any] | None,
) -> str:
    """Build the payload a single playing daily-mod should receive.

    The viewer keeps its real state (already PLAYING by caller contract);
    every other participant is projected to the viewer's IGT so finished
    and concurrent ghosts appear as if running in parallel.
    """
    viewer_igt = viewer.igt_ms or 0
    projected_others: list[Participant | ProjectedParticipant] = []
    for p in participants:
        if p.id == viewer.id:
            continue
        proj = project_participant_at(p, viewer_igt, graph_json)
        if proj is not None:
            projected_others.append(proj)

    sorted_proj, entry_igts = sort_leaderboard([viewer, *projected_others], graph_json=graph_json)
    leader_splits, leader_igt_ms, has_leader = _build_leader_context(sorted_proj, graph_json)
    return _build_leaderboard_payload(
        sorted_proj,
        entry_igts,
        connected_ids=connected_ids,
        graph_json=graph_json,
        leader_splits=leader_splits,
        leader_igt_ms=leader_igt_ms,
        has_leader=has_leader,
    )


# Global connection manager instance
manager = ConnectionManager()
