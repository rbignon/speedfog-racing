"""WebSocket message schemas."""

from typing import Literal

from pydantic import BaseModel

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


class FinishedMessage(BaseModel):
    """Player finished the race."""

    type: Literal["finished"] = "finished"
    igt_ms: int


class EventFlagMessage(BaseModel):
    """Event flag trigger from mod (replaces zone_entered)."""

    type: Literal["event_flag"] = "event_flag"
    flag_id: int
    igt_ms: int


class PongMessage(BaseModel):
    """Heartbeat response from mod."""

    type: Literal["pong"] = "pong"


# --- Server -> Client Messages ---


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


class RaceInfo(BaseModel):
    """Race info for WebSocket."""

    id: str
    name: str
    status: str
    started_at: str | None = None


class SeedInfo(BaseModel):
    """Seed info for WebSocket."""

    total_layers: int
    graph_json: dict[str, object] | None = None  # Only for spectators
    total_nodes: int | None = None
    total_paths: int | None = None
    event_ids: list[int] | None = None


class AuthOkMessage(BaseModel):
    """Successful authentication response."""

    type: Literal["auth_ok"] = "auth_ok"
    participant_id: str
    race: RaceInfo
    seed: SeedInfo
    participants: list[ParticipantInfo]


class AuthErrorMessage(BaseModel):
    """Authentication error response."""

    type: Literal["auth_error"] = "auth_error"
    message: str


class RaceStartMessage(BaseModel):
    """Race start broadcast."""

    type: Literal["race_start"] = "race_start"


class LeaderboardUpdateMessage(BaseModel):
    """Leaderboard update broadcast."""

    type: Literal["leaderboard_update"] = "leaderboard_update"
    participants: list[ParticipantInfo]


class RaceStateMessage(BaseModel):
    """Initial race state for spectators."""

    type: Literal["race_state"] = "race_state"
    race: RaceInfo
    seed: SeedInfo
    participants: list[ParticipantInfo]


class PlayerUpdateMessage(BaseModel):
    """Single player update for spectators."""

    type: Literal["player_update"] = "player_update"
    player: ParticipantInfo


class RaceStatusChangeMessage(BaseModel):
    """Race status change broadcast."""

    type: Literal["race_status_change"] = "race_status_change"
    status: str
    started_at: str | None = None


class SpectatorCountMessage(BaseModel):
    """Spectator count update."""

    type: Literal["spectator_count"] = "spectator_count"
    count: int


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
    exits: list[ExitInfo]


class PingMessage(BaseModel):
    """Heartbeat ping from server."""

    type: Literal["ping"] = "ping"
