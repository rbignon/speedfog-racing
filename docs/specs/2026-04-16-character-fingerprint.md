# Character Fingerprint (Anti Save-Swap)

**Status: not implemented** -- spec only, parked until the problem becomes more frequent.

## Problem

Players occasionally load the wrong save after a quit-out and end up sending data from a different character (stale DefeatFlags, wrong IGT, etc.) to the server. This silently corrupts race and training session data.

This is not about cheating: a tampered mod can spoof anything. The goal is to catch **accidental** save swaps.

## Design

### Fingerprint definition

A character fingerprint is a tuple of three values read from Elden Ring's memory:

| Field            | Memory offset              | Type                                  | Notes                               |
| ---------------- | -------------------------- | ------------------------------------- | ----------------------------------- |
| `starting_class` | `GameDataMan + 0x8 + 0xBF` | u8 (0-9)                              | Immutable after creation            |
| `character_name` | `GameDataMan + 0x8 + 0x9C` | 19 UTF-16 wide-chars, null-terminated | Editable via mods, stable otherwise |
| `save_slot`      | `GameMan + 0xAC0`          | u8 (0-9)                              | Slot index in `ER0000.sl2`          |

Wire format: raw JSON tuple (not hashed), sent on every `status_update` message. Raw format chosen for log debuggability.

```json
{
  "starting_class": 7,
  "character_name": "Tarnished",
  "save_slot": 0
}
```

### Protocol

The `status_update` message gains an optional `character_fingerprint` field:

```json
{
  "type": "status_update",
  "igt_ms": 142300,
  "death_count": 3,
  "character_fingerprint": {
    "starting_class": 7,
    "character_name": "Tarnished",
    "save_slot": 0
  }
}
```

The field is optional (`null` / absent) for backward compatibility with older mod versions. The server must accept messages without a fingerprint.

### Server-side validation

The server stores the fingerprint the first time it sees one per participant (race) or per session (training). On subsequent messages:

1. **Fingerprint absent**: accept (backward compat with older mods).
2. **Fingerprint matches stored**: accept.
3. **Fingerprint differs, `igt_ms < 15000`**: accept and **replace** stored fingerprint. This is the rescue path for a player who legitimately created a fresh character mid-session (IGT resets to 0 on character creation, so IGT < 15s signals a brand new character).
4. **Fingerprint differs, `igt_ms >= 15000`**: **reject**. Send an error message over the WebSocket ("Save file mismatch: you appear to have loaded a different character."). Do not close the connection; the player can reload the correct save and resume.

The fingerprint is stored as a nullable JSON column on the Participant and TrainingSession models.

### Scope

Applies to both competitive races (`/ws/mod/{race_id}`) and solo training sessions (`/ws/training/{session_id}`).

### No admin override

There is no admin button to manually reset a fingerprint. The `igt_ms < 15s` rescue path covers the legitimate case (player recreates a character after a crash). In all other cases, the player simply reloads the correct save.

## Implementation notes

### Mod

- libeldenring (git dependency) does not expose `starting_class`, `character_name`, or `save_slot`. Local `PointerChain`s in `game_state.rs` are needed, following the pattern of `read_deaths()` / `read_igt()`.
- Character name requires reading 38 bytes of UTF-16 and decoding/trimming at the first NUL.
- A `CharacterFingerprint` struct should be added to the shared protocol types in `core/protocol.rs`.
- The fingerprint is read every ~1s alongside IGT/deaths (cheap: three pointer reads) and included in every `status_update`.

### Server

- Alembic migration to add a nullable JSON column to Participant and TrainingSession.
- Pydantic `CharacterFingerprint` model in `websocket/schemas.py`.
- Validation logic as a shared helper on `BaseModHandler`, called at the top of `_handle_status_update` before any state mutation.
- Rejection follows the existing pattern: `_send_error()` + return early, do not close the WebSocket.

### Tests

- First fingerprint is stored.
- Matching fingerprint is accepted.
- Mismatched fingerprint with `igt_ms >= 15000` is rejected with error.
- Mismatched fingerprint with `igt_ms < 15000` replaces the stored one.
- Missing fingerprint (legacy mod) is accepted.
