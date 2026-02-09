# SpeedFog Racing — Roadmap

**Last updated:** 2026-02-09

---

## Completed

### Phase 1 — MVP Foundation

Server foundation, Twitch OAuth, seed pool management, race CRUD, seed pack generation, SvelteKit frontend, race management UI, WebSocket server (mod + spectator), WebSocket frontend, mod fork (Rust DLL), integration testing, protocol coherence.

**Spec:** `docs/specs/phase1.md`

### Phase 2 — UI/UX & DAG Visualization

Metro-style DAG visualization (pure SVG, custom layout algorithm), homepage redesign with animated hero DAG, race detail page overhaul (state-driven layouts for lobby/running/finished), caster role, organizer participation toggle, optional WebSocket auth for DAG visibility, player colors, podium, spectator count, participant search with autocomplete, race creation form with pool cards.

**Spec:** `docs/specs/phase2-ui-ux.md`

### EMEVD Event-Based Zone Tracking

Replaced map_id-based zone tracking with custom EMEVD event flags for precise fog gate traversal detection and automatic race finish on final boss death.

**Spec:** `docs/specs/emevd-zone-tracking.md`

Delivered:

- SpeedFog generator: EMEVD event injection for fog gates + final boss, using category 1040292 (offsets 800-999) co-located with FogRando's runtime category
- graph.json v4 format with `event_map` and `finish_event`
- Mod: `EventFlagReader` with red-black tree traversal of VirtualMemoryFlag, `event_flag` message, reconnect re-scan
- Server: `handle_event_flag` handler, finish detection, `auth_ok` with `event_ids`, server-driven tier computation
- Start zone placement on PLAYING transition
- Event flag debugging tools: file logging (`tracing-appender`), `FlagReaderStatus` diagnostics, debug overlay (F3)

### Mod Overlay Redesign

Compact 2-line header (race+IGT / tier+deaths+progress), color-coded leaderboard (orange=ready, white=playing, green=finished), self-identification via `participant_id` in `auth_ok`, configurable styling (font, colors, border, opacity).

### PROTOCOL.md Rewrite

Full rewrite of the protocol reference to match current implementation: `event_flag` replaces `zone_entered`, `event_ids` in `auth_ok`, spectator WebSocket auth flow, `spectator_count`, all REST endpoints documented.

### Race Management Consolidation

Deleted standalone `/race/[id]/manage` page. All organizer actions moved to race detail sidebar. New `POST /races/{id}/open` endpoint for DRAFT→OPEN transition. Status flow: DRAFT → Open Race → OPEN → Generate Packs + Start Race → RUNNING → FINISHED.

---

## v1.0 — First Real Usage

Everything needed to run an actual race end-to-end with a usable feature set. The core platform is code-complete — remaining items are deployment prep and polish.

### Seed Pool Regeneration

**Priority:** Critical (blocker)

Regenerate all seed pools with the updated SpeedFog generator (event flag base 1040292800). Existing pools lack `event_map` / `finish_event` in graph.json and have no EMEVD event injection.

- Regenerate sprint, standard, marathon pools
- Verify event flags are readable in-game (end-to-end test with a real seed)
- Update hero-seed.json with v4 format (add dummy `event_map` for homepage DAG consistency)

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

- Show pending invites in the race detail sidebar (invited but not yet accepted)
- Visual distinction between confirmed participants and pending invites
- Copy invite link button for each pending invite
- Auto-add participant when invite is accepted (already works server-side)

### Cleanup: Remove `show_finished_names`

**Priority:** Low

The `show_finished_names` config option was proposed in the design doc but never implemented and has no real use case. Remove all references from:

- `docs/DESIGN.md`
- `docs/specs/phase1.md`
- `docs/specs/phase2-ui-ux.md`

No code changes needed — it was never implemented.

---

## v1.1 — Quality of Life

Improvements after initial real-world usage.

### Synchronized Pre-Race Countdown

Coordinated countdown across all mod clients before `race_start`:

- Server broadcasts a `countdown` message with a target timestamp
- Mod displays 3-2-1-GO overlay synchronized to server time
- Accounts for network latency (clients adjust based on round-trip time)
- Optional: countdown visible on spectator WebSocket too

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
