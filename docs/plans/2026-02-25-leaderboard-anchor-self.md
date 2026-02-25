# Leaderboard: Always Show Local Player ("Anchor at Bottom")

## Problem

The in-game overlay leaderboard shows the top 10 players. In races with 11+ participants, a player ranked 11th or below never sees themselves on screen.

## Design

### Display Logic

**Case 1 — 10 or fewer participants:** Show all. No change.

**Case 2 — 11+ participants, local player in top 10:** Show top 10 + "+ N more". No change.

**Case 3 — 11+ participants, local player beyond top 10:**

```
 1. PlayerOne           3/8
 2. AnotherGuy          3/8
 ...
 9. SomePlayer          2/8
  ···
14. MyName              1/8
  + 6 more
```

- Show **top 9** (one fewer to make room)
- Separator line `···` (disabled/gray color)
- Local player's row at their **real rank** in the sorted list
- `+ N more` = total - 10 displayed (9 top + 1 self)

### Local Player Highlight

- The local player's name is rendered in **cyan** `[0.0, 1.0, 1.0, 1.0]` regardless of status
- Applies in **all cases** (whether in top 10 or anchored at bottom)
- Cyan is distinct from existing status colors (orange=ready, white=playing, green=finished)

### Scope

Single file change: `mod/src/dll/ui.rs`, function `render_leaderboard`.

1. Find local player's index in `participants` via `my_participant_id`
2. Determine display mode (show all vs anchor)
3. Render loop with cyan highlight for local player
4. If anchoring: `···` separator + local player row + adjusted "more" count

No server changes, no protocol changes, no new WebSocket messages.
