# SpeedFog Racing — Roadmap

**Last updated:** 2026-02-07

---

## Completed

### Phase 1 — MVP Foundation

Server foundation, Twitch OAuth, seed pool management, race CRUD, seed pack generation, SvelteKit frontend, race management UI, WebSocket server (mod + spectator), WebSocket frontend, mod fork (Rust DLL), integration testing, protocol coherence.

**Spec:** `docs/specs/phase1.md`

### Phase 2 — UI/UX & DAG Visualization

Metro-style DAG visualization (pure SVG, custom layout algorithm), homepage redesign with animated hero DAG, race detail page overhaul (state-driven layouts for lobby/running/finished), caster role, organizer participation toggle, optional WebSocket auth for DAG visibility, player colors, podium, spectator count, participant search with autocomplete, race creation form with pool cards.

**Spec:** `docs/specs/phase2-ui-ux.md`

---

## v1.0 — First Real Usage

Everything needed to run an actual race end-to-end with accurate tracking and a usable feature set.

### EMEVD Event-Based Zone Tracking

**Priority:** Critical (blocker)
**Spec:** `docs/specs/emevd-zone-tracking.md`

Replace map_id-based zone tracking with custom EMEVD event flags for precise fog gate traversal detection and automatic race finish on final boss death. Requires changes to the SpeedFog generator, the racing mod, and the server.

Key deliverables:

- SpeedFog generator: EMEVD event injection for fog gates + final boss
- graph.json v4 format with `event_map` and `finish_event`
- Mod: event flag reading from game memory, new `event_flag` message
- Server: `handle_event_flag` handler, finish detection, auth_ok with `event_ids`
- Seed pool regeneration

### OBS Overlays

**Priority:** High

Dedicated pages for OBS with transparent backgrounds, reusing existing components:

- `/overlay/{id}/leaderboard` — vertical leaderboard with player colors, transparent background
- `/overlay/{id}/dag` — metro DAG with live player positions, transparent background

Both are thin wrappers around `Leaderboard.svelte` and `MetroDagLive.svelte` with `background: transparent` and no page chrome. Visible to organizers and casters on the race detail page as direct links.

### Admin Seed Dashboard (Frontend)

**Priority:** Medium

Frontend page for the existing `/api/admin/seeds` endpoint. Displays pool statistics:

- Available / consumed seed counts per pool
- Rescan button (calls `POST /api/admin/seeds/scan`)
- Pool metadata (display name, estimated duration)

Accessible to admin users only. Simple table layout, no complex UI needed.

### Invite UX Polish

**Priority:** Medium

The invite system backend exists (Phase 1 Step 12) but the UX flow is incomplete:

- Show pending invites on the manage page (invited but not yet accepted)
- Visual distinction between confirmed participants and pending invites
- Copy invite link button for each pending invite
- Auto-add participant when invite is accepted (already works server-side)

### Cleanup: Remove `show_finished_names`

**Priority:** Low

The `show_finished_names` config option was proposed in the design doc but never implemented and has no real use case (hiding finished player names doesn't add meaningful anti-spoiler value). Remove all references from:

- `docs/DESIGN.md`
- `docs/specs/phase1.md`
- `docs/specs/phase2-ui-ux.md`

No code changes needed — it was never implemented.

### Mod Debug Overlay

**Priority:** Low

Optional debug panel in the mod's ImGui overlay for troubleshooting:

- WebSocket connection status and message counts
- Last event flags triggered
- Current game state readings (IGT, death count, map_id)
- Server round-trip latency

Toggle via a hotkey (e.g., F10). Useful during testing and for players reporting issues.

---

## v1.1 — Quality of Life

Improvements after initial real-world usage.

### Synchronized Pre-Race Countdown

Coordinated countdown across all mod clients before `race_start`:

- Server broadcasts a `countdown` message with a target timestamp
- Mod displays 3-2-1-GO overlay synchronized to server time
- Accounts for network latency (clients adjust based on round-trip time)
- Optional: countdown visible on spectator WebSocket too

### PROTOCOL.md Cleanup

Update the protocol reference to reflect all v1.0 changes:

- Replace `zone_entered` with `event_flag`
- Remove `current_zone` from `status_update`
- Document `event_ids` in `auth_ok`
- Remove the "Phase 2 Extensions (Planned)" section for `zone_info` (superseded by EMEVD approach)
- Add `spectator_count` message documentation
- Document optional spectator WebSocket auth flow

---

## v2.0 — Advanced Features

Larger scope features for after the platform is established.

### Progressive Path Display

Show players the portions of the DAG they've already discovered during a running race. Requires the server to send a filtered view of the DAG containing only discovered nodes and edges. Enriches the player experience without spoiling the full graph.

### On-Demand Seed Generation

Generate seeds dynamically on the server instead of pre-generated pools. Requires running the SpeedFog generator server-side (likely via Wine on Linux). Eliminates pool management overhead and enables unlimited races.

### Server-Side Zone Info for Mod

Enrich the mod overlay with discovered exit information computed server-side. The server tracks which exits the player has found and sends display-friendly zone names and directions. Allows the mod to show "Exits: Caelid Gaol Cave (origin), ??? (undiscovered)" without exposing the full graph.

### Custom EMEVD Events (Enhanced)

Beyond basic fog gate tracking, add EMEVD events for:

- Boss defeat detection per zone (not just final boss)
- Item pickup tracking (key items, Great Runes)
- More granular progress milestones

### Mod Overlay Template System

Configurable templates for customizing how race status and player info are displayed in the mod overlay. Allows streamers to match their overlay style.

---

## Future / Unscoped

Ideas that may or may not happen, depending on community growth.

| Idea                             | Description                                                                                    |
| -------------------------------- | ---------------------------------------------------------------------------------------------- |
| **Brackets / Tournaments**       | Multi-race tournament bracket system with seeding and elimination                              |
| **Historical Player Statistics** | Win rates, average times, fastest runs, personal records across races                          |
| **Asynchronous Races**           | Players start at different times, compete on IGT. Requires rethinking the spectator experience |
