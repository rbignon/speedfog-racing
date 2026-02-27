# Overlay Improvements Design

**Date:** 2026-02-27
**Status:** Approved

## Goals

Improve the streamer experience for OBS overlays (leaderboard and DAG) with better configurability and live race tracking.

## 1. Leaderboard — Top N Lines

**URL:** `/overlay/race/{id}/leaderboard?lines=10`

**Parameter:** `lines` (integer, default 10). Only the top N participants from the live leaderboard are rendered. If cleared/absent, defaults to 10. The streamer can remove the parameter (or set a high value) to show all participants.

**Implementation:** `LeaderboardOverlay.svelte` slices the `leaderboard` array to `lines` before rendering.

**Modal:** Numeric input "Number of lines" in `ObsOverlayModal`, default 10, clearable for unlimited. Updates the generated URL in real time.

## 2. DAG Pre-Race — Visible Structure, Hidden Labels

Replace `MetroDagBlurred` with a real DAG render (using `MetroDagFull`) when `graph_json` is available during setup.

- Nodes: real shapes and positions from `graph_json`
- Edges: visible
- Labels: replaced with `???` or hidden entirely (new `hideLabels` prop)
- No blur, no reduced opacity

**Benefit:** The streamer calibrates their OBS overlay on the actual DAG layout. When the race starts, only labels appear — no layout shift.

**Fallback:** If `graph_json` is not yet available during setup, fall back to `MetroDagBlurred`.

## 3. DAG Auto-Zoom — Follow Mode

**URL:** `/overlay/race/{id}/dag?follow=true`

**Parameter:** `follow` (boolean, default `false`). When enabled, the viewport automatically tracks player progression.

**Modal:** Checkbox "Auto-follow" in `ObsOverlayModal`, unchecked by default.

### Behavior by race status

**Setup (follow=true):**

- Viewport zoomed in on the first layer, same zoom level as race start
- Player dots aligned left of the start node (symmetrical with finished dots on the right)
- Manual zoom/pan disabled — streamer sees the exact rendering they'll get at race start
- Seamless transition when the race begins

**Running (follow=true):**

1. Compute barycenter X of all active (`playing`) participants based on `current_layer`
2. Compute zoom to encompass all active players with margin
3. If required zoom exceeds zoom min (too many layers to show), clamp to zoom min and center on barycenter
4. Animated transition (~1s ease-out) on each leaderboard update
5. Manual zoom/pan disabled

**Finished (follow=true):**

- Zoom out to show the complete DAG — final view of all player paths
- Player dots for finished players aligned right of the final boss node

**Any status (follow=false):**

- Current behavior: manual zoom/pan via `ZoomableSvg`

### Zoom limits

**Zoom min:** Dynamically calculated so that at most ~50% of total layers are visible at once. For an 8-layer seed → max 4 visible; for 12 layers → max 6. No `maxLayers` parameter exposed in v1; can be added later if requested.

**Centering bounds:** The viewport cannot center beyond the first layer (left edge) or the last layer (right edge), preventing empty space at the extremes.

### Off-screen indicators

When a `playing` participant is outside the visible viewport:

- Colored chevron (player color from `PLAYER_COLORS`) pinned to the left or right edge
- Player name next to the chevron
- Y position aligned with the player's layer for vertical context

## 4. DAG Visual Parity with ReplayDag

Bring the live overlay DAG in line with the ReplayDag visuals:

- **Player dots:** Orbiting around nodes when a player is at that node (same animation as ReplayDag)
- **Death skulls:** Skull icon appears on death events
- **Start alignment:** During setup and race start, player dots aligned left of the start node
- **Finish alignment:** Finished player dots aligned right of the final boss node

### Path lines

Behavior depends on follow mode:

**follow=false:** Full colored path lines (current behavior). Shows complete traversal history.

**follow=true:** Trailing transparency effect. Only the last few segments of each player's path are visible, with progressive opacity:

- Current segment: 100% opacity
- Previous segment: ~50%
- Two segments back: ~20%
- Older: hidden

This provides directional context ("where they came from, where they're going") without visual clutter in a zoomed-in viewport. Implemented via `stroke-opacity` gradient on polyline segments, derived from `zone_history`.

## 5. ObsOverlayModal Updates

**Leaderboard section:**

- Numeric input: "Number of lines" (default 10, clearable)

**DAG section:**

- Checkbox: "Auto-follow" (default unchecked)

Both fields update the displayed URL in real time. The streamer copies the final URL to OBS.
