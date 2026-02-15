# OBS Overlay for Casters — Design

## Summary

Add OBS-compatible overlay pages for casters to display the race DAG and leaderboard on their streams. Two separate transparent-background pages, no authentication required.

## Routes

- `/overlay/race/[id]/dag` — real-time DAG visualization, transparent background
- `/overlay/race/[id]/leaderboard` — real-time leaderboard, transparent background

Dedicated `/overlay/` layout group with no navbar, no footer, no global styles.

## Authentication

None. Overlays connect as anonymous spectators via the existing spectator WebSocket. The `graph_json` is only available from RUNNING onwards (existing server behavior). Before that, a blurred teaser is shown.

## DAG Overlay Flow

| Race Status  | Component       |
| ------------ | --------------- |
| DRAFT / OPEN | MetroDagBlurred |
| RUNNING      | MetroDagResults |
| FINISHED     | MetroDagResults |

MetroDagResults shows colored trails (zone_history) in real-time during RUNNING, giving casters and viewers a clear view of each player's path through the graph as it happens.

## Race Detail Page Change

The spectator/caster view on the main race page also switches from MetroDagLive to MetroDagResults during RUNNING, for consistency:

| Status       | Participant         | Spectator / Caster |
| ------------ | ------------------- | ------------------ |
| DRAFT / OPEN | MetroDagProgressive | MetroDagBlurred    |
| RUNNING      | MetroDagProgressive | MetroDagResults    |
| FINISHED     | MetroDagResults     | MetroDagResults    |

MetroDagLive is kept in the codebase but no longer actively used. It can be restored if MetroDagResults proves too busy with many participants.

## New Components

### LeaderboardOverlay.svelte

Dedicated overlay-optimized leaderboard component:

- Transparent background
- White text with strong `text-shadow` (double shadow for readability on any stream background)
- Color dot per player (`PLAYER_COLORS[color_index]`) + display name + stats
- Running mode: current layer / total layers + IGT + death count
- Finished mode: placement (medals for top 3) + final IGT + death count
- Vertical flex layout, no scroll, no interactivity

### OBS Overlay Modal

Triggered by an "OBS Overlays" button in the race detail sidebar, visible to casters and the organizer:

- Two sections (DAG + Leaderboard), each with:
  - Read-only input showing the full overlay URL
  - "Copy" button
  - Recommended OBS Browser Source size (DAG: 800×600, Leaderboard: 400×800)
- URLs built client-side: `window.location.origin + /overlay/race/{id}/dag|leaderboard`

## Overlay Page Structure

Both overlay pages:

- Load race data via REST API (`+page.ts`, same as race detail page)
- Connect to spectator WebSocket via `raceStore`
- Render a single component full-viewport (`width: 100%; height: 100vh`)
- `background: transparent`, `overflow: hidden`
- No scroll, no interactivity

## Server Changes

None. The feature relies entirely on the existing spectator WebSocket and REST API.

## Decisions

- **No auth for overlays**: simpler, no token-in-URL security concern. Casters see MetroDagBlurred before race starts (same as anonymous spectators).
- **Two separate overlays** (not combined): casters prefer independent OBS sources they can position/resize freely.
- **No DAG mode selector**: automatic flow (Blurred → Results → Results) removes configuration complexity.
- **Dedicated LeaderboardOverlay component**: overlay context (transparent bg, stream readability) is too different from sidebar leaderboard to share a component.
- **MetroDagResults for RUNNING**: colored trails are more informative than position dots (MetroDagLive) for both casting and spectating.
