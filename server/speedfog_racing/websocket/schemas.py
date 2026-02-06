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
    current_zone: str
    death_count: int


class ZoneEnteredMessage(BaseModel):
    """Player entered a new zone."""

    type: Literal["zone_entered"] = "zone_entered"
    from_zone: str
    to_zone: str
    igt_ms: int


class FinishedMessage(BaseModel):
    """Player finished the race."""

    type: Literal["finished"] = "finished"
    igt_ms: int


# --- Server -> Client Messages ---


class ParticipantInfo(BaseModel):
    """Participant info for leaderboard."""

    id: str
    twitch_username: str
    twitch_display_name: str | None
    status: str
    current_zone: str | None
    current_layer: int
    igt_ms: int
    death_count: int


class RaceInfo(BaseModel):
    """Race info for WebSocket."""

    id: str
    name: str
    status: str


class SeedInfo(BaseModel):
    """Seed info for WebSocket."""

    total_layers: int
    graph_json: dict[str, object] | None = None  # Only for spectators


class AuthOkMessage(BaseModel):
    """Successful authentication response."""

    type: Literal["auth_ok"] = "auth_ok"
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
