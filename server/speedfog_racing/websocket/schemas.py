"""WebSocket message schemas."""

import uuid
from datetime import UTC, date, datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from speedfog_racing.models import ChatChannel

from pydantic import BaseModel, Field

from speedfog_racing.models import compute_late_join_deadlines

# --- Client -> Server Messages (Mod) ---


class AuthMessage(BaseModel):
    """Mod authentication message."""

    type: Literal["auth"] = "auth"
    mod_token: str


class ReadyMessage(BaseModel):
    """Player ready signal."""

    type: Literal["ready"] = "ready"


class StatusUpdateMessage(BaseModel):
    """Periodic status update from mod."""

    type: Literal["status_update"] = "status_update"
    igt_ms: int
    death_count: int
    # [left_hand, right_hand] raw runtime weapon IDs (EquipParamWeapon row + upgrade).
    # None per slot means empty hand, two-handed mask on the inactive side, or loading
    # screen. Field-level None means an older mod build that doesn't report weapons.
    weapons: tuple[int | None, int | None] | None = None


class EventFlagMessage(BaseModel):
    """Event flag trigger from mod (replaces zone_entered)."""

    type: Literal["event_flag"] = "event_flag"
    flag_id: int
    igt_ms: int
    message_id: int | None = None


class PongMessage(BaseModel):
    """Heartbeat response from mod."""

    type: Literal["pong"] = "pong"


class SpawnItem(BaseModel):
    """Item to be spawned at runtime by the mod (e.g., Gem/Ash of War)."""

    id: int
    qty: int = 1


class PhantomSkinDirective(BaseModel):
    """Directives the mod should apply when the user equips a given skin name.

    Forward-compatible: unknown keys are ignored by the mod, missing keys are no-ops.
    V1 ships only `speffects`.
    """

    speffects: list[int] = Field(default_factory=list)


def extract_phantom_skins(
    graph_json: dict[str, Any],
) -> dict[str, PhantomSkinDirective]:
    """Extract the per-seed phantom_skins map from graph.json.

    Older seeds without the field return an empty dict; the mod treats that as
    "feature off for this seed" and silently no-ops on any push.
    """
    raw = graph_json.get("phantom_skins") or {}
    out: dict[str, PhantomSkinDirective] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            continue
        speffects = entry.get("speffects") or []
        if not isinstance(speffects, list):
            continue
        out[name] = PhantomSkinDirective(
            speffects=[int(x) for x in speffects if isinstance(x, int)],
        )
    return out


def extract_spawn_items(graph_json: dict[str, Any]) -> list[SpawnItem]:
    """Extract type-4 (Gem/Ash of War) items from care_package for mod runtime spawning."""
    care_pkg = graph_json.get("care_package", [])
    return [
        SpawnItem(id=item["id"], qty=1)
        for item in care_pkg
        if item.get("type") == 4 and item.get("id", 0) != 0
    ]


# --- Server -> Client Messages ---


class NameTemplatePayload(BaseModel):
    """Mod-side render payload for a name template (color/gradient only).

    Background CSS is web-only and is not transmitted over WebSocket.
    """

    color: str | None = None
    gradient: list[str] | None = None


class ParticipantInfo(BaseModel):
    """Participant info for leaderboard."""

    id: str
    twitch_username: str
    twitch_display_name: str | None
    status: str
    current_zone: str | None
    current_layer: int
    current_layer_tier: int | None = None
    igt_ms: int
    death_count: int
    color_index: int = 0
    mod_connected: bool = False
    zone_history: list[dict[str, object]] | None = None
    gap_ms: int | None = None
    layer_entry_igt: int | None = None
    is_live: bool = False
    stream_url: str | None = None
    equipped_badge_id: str | None = None
    equipped_name_template_id: str | None = None
    name_template: NameTemplatePayload | None = None
    # Per-rank Daily Seed points, only set on a FINISHED daily (null otherwise).
    daily_points: int | None = None


class RaceInfo(BaseModel):
    """Race info for WebSocket.

    Carries every race-level field that can be displayed by a connected client
    so the same payload feeds both initial state (auth_ok / race_state) and
    live updates (race_info_update emitted on PATCH /races).
    """

    id: str
    name: str
    status: str
    is_public: bool = True
    open_registration: bool = False
    max_participants: int | None = None
    scheduled_at: str | None = None
    started_at: str | None = None
    seeds_released_at: str | None = None
    late_join_window_minutes: int | None = None
    race_duration_minutes: int | None = None
    registration_closes_at: str | None = None
    race_ends_at: str | None = None
    private_dag: bool = False
    countdown_seconds: int = 0
    # Current seed FK, so a connected mod can detect that its loaded seed pack
    # went stale after a reroll (it compares this against its config seed_id).
    seed_id: str | None = None


def build_race_info(race: Any, *, countdown_seconds: int = 0) -> "RaceInfo":
    """Build a RaceInfo from a Race ORM model.

    Centralized so the auth_ok handshake, the race_state broadcast, and the
    race_info_update broadcast all serialize the same set of fields. The two
    absolute deadlines are computed from ``started_at + duration`` so clients
    never duplicate the math.
    """
    registration_closes_at, race_ends_at = compute_late_join_deadlines(race)
    return RaceInfo(
        id=str(race.id),
        name=race.name,
        status=race.status.value,
        is_public=race.is_public,
        open_registration=race.open_registration,
        max_participants=race.max_participants,
        scheduled_at=race.scheduled_at.isoformat() if race.scheduled_at else None,
        started_at=race.started_at.isoformat() if race.started_at else None,
        seeds_released_at=(race.seeds_released_at.isoformat() if race.seeds_released_at else None),
        late_join_window_minutes=race.late_join_window_minutes,
        race_duration_minutes=race.race_duration_minutes,
        registration_closes_at=(
            registration_closes_at.isoformat() if registration_closes_at else None
        ),
        race_ends_at=race_ends_at.isoformat() if race_ends_at else None,
        private_dag=race.private_dag,
        countdown_seconds=countdown_seconds,
        seed_id=str(race.seed_id) if race.seed_id else None,
    )


class SeedInfo(BaseModel):
    """Seed info for WebSocket."""

    seed_id: str | None = None
    total_layers: int
    graph_json: dict[str, object] | None = None  # Full graph for client-side progressive reveal
    total_nodes: int | None = None
    total_paths: int | None = None
    event_ids: list[int] = Field(default_factory=list)
    finish_event: int | None = None
    spawn_items: list[SpawnItem] = Field(default_factory=list)
    death_flags: dict[str, list[int]] = Field(default_factory=dict)
    items_spawned_flag: int | None = None
    phantom_skins: dict[str, PhantomSkinDirective] = Field(default_factory=dict)


def resolve_phantom_skin_for_auth_ok(equipped: str | None) -> str | None:
    """None or the literal 'none' resolves to None; anything else passes through."""
    if equipped is None or equipped == "none":
        return None
    return equipped


class AuthOkMessage(BaseModel):
    """Successful authentication response."""

    type: Literal["auth_ok"] = "auth_ok"
    participant_id: str
    race: RaceInfo
    seed: SeedInfo
    participants: list[ParticipantInfo]
    phantom_skin: str | None = None


class AuthErrorMessage(BaseModel):
    """Authentication error response."""

    type: Literal["auth_error"] = "auth_error"
    message: str


class ErrorMessage(BaseModel):
    """Generic error sent during the message loop (not auth phase)."""

    type: Literal["error"] = "error"
    message: str


class DeathCountsMessage(BaseModel):
    """Aggregated death counts per zone, broadcast to mods."""

    type: Literal["death_counts"] = "death_counts"
    counts: dict[str, int]  # node_id -> total deaths across all participants


class RaceStartMessage(BaseModel):
    """Race start broadcast."""

    type: Literal["race_start"] = "race_start"
    countdown_seconds: int = 0


class LeaderboardUpdateMessage(BaseModel):
    """Leaderboard update broadcast."""

    type: Literal["leaderboard_update"] = "leaderboard_update"
    participants: list[ParticipantInfo]
    leader_splits: dict[int, int] | None = None


class DailyStreakUpdateMessage(BaseModel):
    """Unicast to a user when their daily streak state changes.

    Sent on Update A (the user just crossed ``len(zone_history) >= 2`` on a
    daily race) and on the explicit-abandon trigger (close-day branch
    applied immediately). Not broadcast to spectators; not sent for
    non-daily races.

    ``freeze_consumed_for`` is set to the ``daily_date`` of the affected
    daily when this message reports a freeze consumption (currently the
    abandon trigger). The frontend uses it to patch
    ``DailyWeekDay.freeze_protected`` for the matching cell so the strip
    flips to "❄️ Freeze" without waiting for a page reload. ``None`` on
    every other case (qualification crossing, future triggers).
    """

    type: Literal["daily_streak_update"] = "daily_streak_update"
    current: int
    best: int
    freeze_count: int
    freeze_consumed_for: date | None = None


class PendingInviteInfo(BaseModel):
    """Public projection of a pending invite shipped over WebSocket.

    The opaque accept token is intentionally absent: it is sensitive (anyone
    holding it can claim the slot) and only the organizer needs it, fetched
    via REST GET /races/:id. The WS payload only carries what every client
    needs to render the "still waiting on" list.
    """

    id: str
    twitch_username: str
    created_at: str


class RaceStateMessage(BaseModel):
    """Initial race state for spectators."""

    type: Literal["race_state"] = "race_state"
    race: RaceInfo
    seed: SeedInfo
    participants: list[ParticipantInfo]
    pending_invites: list[PendingInviteInfo] = Field(default_factory=list)


class RaceInfoUpdateMessage(BaseModel):
    """Live update of race-level info, broadcast to mod and spectator clients.

    Emitted by PATCH /races whenever a RaceInfo field changes so connected
    clients keep their cached race state in sync without reconnecting.
    """

    type: Literal["race_info_update"] = "race_info_update"
    race: RaceInfo


class PlayerUpdateMessage(BaseModel):
    """Single player update for spectators."""

    type: Literal["player_update"] = "player_update"
    player: ParticipantInfo


class RaceStatusChangeMessage(BaseModel):
    """Race status change broadcast."""

    type: Literal["race_status_change"] = "race_status_change"
    status: str
    started_at: str | None = None
    countdown_seconds: int | None = None


class SpectatorCountMessage(BaseModel):
    """Spectator count update."""

    type: Literal["spectator_count"] = "spectator_count"
    count: int


class ZoneHistoryMessage(BaseModel):
    """Full zone_history snapshot for a single participant.

    Emitted whenever the server's view of a participant's zone_history
    changes: new entry appended (spawn, fog gate, zone_query backtrack)
    or an existing entry's deaths count updated via death attribution.
    The client replaces its locally-held history for this participant
    with the payload. Sending the full list is self-healing: a client
    that missed an earlier message still ends up with the correct state
    on the next emission.
    """

    type: Literal["zone_history"] = "zone_history"
    participant_id: str
    history: list[dict[str, object]]


class ExitInfo(BaseModel):
    """Exit info for zone_update message."""

    text: str
    to_name: str
    discovered: bool


class ZoneUpdateMessage(BaseModel):
    """Unicast zone update sent to originating mod."""

    type: Literal["zone_update"] = "zone_update"
    node_id: str
    display_name: str
    tier: int | None = None
    original_tier: int | None = None
    layer: int | None = None
    is_first_visit: bool = False
    exits: list[ExitInfo]
    message_id: int | None = None


class EventFlagAckMessage(BaseModel):
    """Acknowledges persistence of an event_flag message."""

    type: Literal["event_flag_ack"] = "event_flag_ack"
    message_id: int


class ZoneQueryAckMessage(BaseModel):
    """Acknowledges a zone_query that could not produce a zone_update."""

    type: Literal["zone_query_ack"] = "zone_query_ack"
    message_id: int


class PingMessage(BaseModel):
    """Heartbeat ping from server."""

    type: Literal["ping"] = "ping"


# --- Client -> Server Messages (Chat) ---


class SendChatMessage(BaseModel):
    """Chat message from authenticated spectator/caster."""

    type: Literal["chat"] = "chat"
    channel: str = Field(pattern=r"^(participants|public)$")
    message: str = Field(max_length=500)


class RequestChatHistoryMessage(BaseModel):
    """Client request to (re)load history for a chat channel.

    Sent by the frontend when a viewer's local access state transitions
    from locked to readable: the late-join window expired, the viewer
    just finished or abandoned, etc. The server is authoritative and
    revalidates access before sending the history; if access is still
    refused, the request is ignored silently.
    """

    type: Literal["request_chat_history"] = "request_chat_history"
    channel: str = Field(pattern=r"^(participants|public)$")


# --- Server -> Client Messages (Chat) ---


class ChatBroadcastMessage(BaseModel):
    """Chat message broadcast to room."""

    type: Literal["chat_message"] = "chat_message"
    channel: str  # "participants" | "public"
    username: str
    display_name: str | None
    avatar_url: str | None
    role: str  # "organizer" | "admin" | "caster" | "participant"
    dominant_trait: str | None  # e.g. "rusher", "explorer", null
    equipped_badge_id: str | None = None
    equipped_name_template_id: str | None = None
    message: str
    timestamp: str  # ISO format from server


class ChatHistoryMessage(BaseModel):
    """Chat history sent on connection for a specific channel."""

    type: Literal["chat_history"] = "chat_history"
    channel: str  # "participants" | "public"
    messages: list[ChatBroadcastMessage]


def system_chat_message(channel: str, message: str) -> str:
    """Build a system chat message JSON string for broadcasting (not persisted)."""
    return ChatBroadcastMessage(
        channel=channel,
        username="",
        display_name=None,
        avatar_url=None,
        role="system",
        dominant_trait=None,
        message=message,
        timestamp=datetime.now(UTC).isoformat(),
    ).model_dump_json()


async def persist_system_chat(
    db: "AsyncSession",
    race_id: uuid.UUID,
    channel: "ChatChannel",
    message: str,
) -> str:
    """Persist a system chat message to DB and return the broadcast JSON.

    The caller is responsible for broadcasting the returned JSON string
    to the appropriate room channel.

    `created_at` is stamped Python-side so that successive calls produce
    monotonically increasing timestamps: the `server_default=func.now()`
    on ChatMessage maps to PostgreSQL `transaction_timestamp()` (shared
    across a whole transaction) and to SQLite `CURRENT_TIMESTAMP`
    (1-second resolution), neither of which preserves insertion order
    for rows flushed close together.
    """
    from speedfog_racing.models import ChatChannel as ChatChannelModel
    from speedfog_racing.models import ChatMessage

    db_msg = ChatMessage(
        race_id=race_id,
        channel=ChatChannelModel(channel) if isinstance(channel, str) else channel,
        user_id=None,
        message=message,
        created_at=datetime.now(UTC),
    )
    db.add(db_msg)
    await db.flush()

    return system_chat_message(channel if isinstance(channel, str) else channel.value, message)
