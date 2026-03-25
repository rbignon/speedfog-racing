# Fresh Save Validation

## Problem

When a player joins a race or training session by loading a pre-existing save (not a fresh "New Game"), several things break:

1. **IGT is inflated**: the in-game timer is already minutes/hours in. All zone entry timestamps, gap timing, and splits are meaningless.
2. **zone_query on load**: the player is physically located somewhere in the game world. On loading screen exit, the mod sends a `zone_query` that may resolve to a DAG node, creating a ghost zone visit.
3. **Death misattribution**: if a ghost zone entry exists in `zone_history`, early deaths get attributed to it.

Event flags are runtime-only (not persisted in save files), so stale flag contamination is not a concern.

## Design

### Server: IGT gate on READY to PLAYING transition

In `handle_status_update` (`websocket/mod.py`), **before** the `igt_ms` write (line 397), check whether this is a READY participant with stale IGT:

- If `participant.status == READY` and `race.status == RUNNING` and `msg["igt_ms"] > MAX_FRESH_IGT_MS` (15 000ms):
  - Log a warning (once per participant, subsequent rejections at debug level)
  - Send `error` message with payload `"Please start a New Game to race"` to the mod
  - Return early (no IGT write, no DB commit, no transition, no broadcast)
- Otherwise: proceed as today

Placing the check before the IGT write avoids transient state mutation on the participant object.

**Threshold rationale:** a fresh Elden Ring save reaches the first loading screen at ~3-5s IGT. 15s gives generous margin for slow machines while catching any real pre-existing save (minutes/hours of IGT).

**Self-healing:** the participant stays in READY status. Each subsequent `status_update` hits the same check. When the player starts a new game (from the main menu, without closing the game), the IGT resets to 0, the next `status_update` passes the check, and the transition proceeds normally.

### Server: guards on event_flag and zone_query

Simplify the participant status check in `handle_event_flag` and `handle_zone_query` to:

```python
if participant.status != ParticipantStatus.PLAYING:
    return
```

This replaces the current enumeration of FINISHED/ABANDONED and also covers READY and REGISTERED, preventing zone_history mutations while the player is stuck in READY with a stale save.

### Mod: display error messages on overlay

The `IncomingMessage::Error` handler currently only logs to debug and tracing. Add a `set_status` call so the player sees the message:

```rust
IncomingMessage::Error(e) => {
    self.last_received_debug = Some(format!("error({})", e));
    warn!(error = %e, "[WS] Error");
    self.set_status(e);  // Display on overlay (yellow, 3s)
}
```

Since `status_update` is sent every ~1s and the server re-rejects each time, the banner stays continuously visible. When the player starts a new game, the server stops rejecting, and the banner expires naturally after 3s.

This also makes other existing error messages visible ("Race not running", etc.), which is desirable.

### Training: IGT gate on first zone_history initialization

In `_handle_status_update` (`websocket/training_mod.py`), at the `if not session.zone_history:` check (line 340), apply the same IGT gate:

- If `not session.zone_history` and `msg["igt_ms"] > MAX_FRESH_IGT_MS` (15 000ms):
  - Log a warning (once per session, subsequent rejections at debug level)
  - Send `error` message with payload `"Please start a New Game"` to the mod
  - Return early (no IGT write, no DB commit, no zone_history initialization)
- Otherwise: proceed as today

**Resumption safe:** training sessions are resumable. If `zone_history` already has entries, the session was previously initialized on a valid save, so the IGT gate does not apply. Only the first initialization (empty zone_history) is gated.

**Self-healing:** same as race mode. The player can start a new game without disconnecting, and the next `status_update` with low IGT will pass the check.

### Logging

To avoid log spam (the server rejects ~1/s while the player has a stale save):

- First rejection for a given participant/session: `logger.warning`
- Subsequent rejections: `logger.debug`

Race mode: track with a `stale_save_warned: set[uuid.UUID]` local to `handle_mod_websocket`, passed to `handle_status_update` as a parameter. Cleaned up automatically when the connection closes.

Training mode: same pattern, local to `handle_training_mod_websocket`.

## Scope

- **Server changes**: `server/speedfog_racing/websocket/mod.py`
  - `handle_status_update`: IGT gate before READY to PLAYING transition
  - `handle_event_flag`: replace FINISHED/ABANDONED check with `!= PLAYING`
  - `handle_zone_query`: add `!= PLAYING` guard
- **Server changes**: `server/speedfog_racing/websocket/training_mod.py`
  - `_handle_status_update`: IGT gate before first zone_history initialization
- **Mod changes**: `mod/src/dll/tracker.rs`
  - `IncomingMessage::Error` handler: add `set_status(e)` call
- **Frontend changes**: none
- **Protocol changes**: none (reuses existing `error` message type with human-readable text)
- **Tests**: add test cases for stale save rejection and self-healing (race + training)
