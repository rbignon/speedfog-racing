"""WebSocket handlers for SpeedFog Racing."""

from speedfog_racing.websocket.race.manager import ConnectionManager, manager
from speedfog_racing.websocket.race.mod import broadcast_race_start, handle_mod_websocket
from speedfog_racing.websocket.race.spectator import (
    broadcast_race_info_update,
    broadcast_race_state_update,
    handle_spectator_websocket,
)
from speedfog_racing.websocket.training.manager import training_manager
from speedfog_racing.websocket.training.mod import handle_training_mod_websocket
from speedfog_racing.websocket.training.spectator import handle_training_spectator_websocket

__all__ = [
    "ConnectionManager",
    "manager",
    "handle_mod_websocket",
    "handle_spectator_websocket",
    "broadcast_race_start",
    "broadcast_race_state_update",
    "broadcast_race_info_update",
    "training_manager",
    "handle_training_mod_websocket",
    "handle_training_spectator_websocket",
]
