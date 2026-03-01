# Solo OBS Overlay — Design

**Date:** 2026-03-01
**Status:** Approved

## Goal

Add an OBS overlay for Solo (training) sessions, showing the MetroDag with live player position — equivalent to the existing race DAG overlay.

## Scope

- DAG overlay only (no leaderboard overlay for solo)
- Same options as race overlay (auto-follow, maxLayers)
- Configuration modal accessible from the solo session detail page

## Design

### Route: `/overlay/training/[id]/dag/`

New SvelteKit page under the existing `/overlay/` layout (transparent background, no scrollbars).

- Connects to training spectator WebSocket via `trainingStore.connect(id)`
- Renders `MetroDagFull` with:
  - `transparent=true`
  - `follow` and `maxLayers` from query params (same defaults as race)
  - `showLiveDots=true`
  - `participants` = `[trainingStore.participant]` (wrapped in array)
- States:
  - Active session → live dot tracking player position
  - Finished/abandoned → static DAG with final path
- No ghosts displayed in the overlay

### Modal: adapt `ObsOverlayModal`

Add a `mode: 'race' | 'training'` prop to the existing `ObsOverlayModal` component:

- `mode === 'training'`: hide leaderboard section, generate training URL base path
- `mode === 'race'` (default): unchanged behavior
- DAG section unchanged: auto-follow checkbox + maxLayers slider
- URL generation: `/overlay/training/{id}/dag?follow=true&maxLayers=5`

### Button in solo session page

Add "OBS Overlay" button in `/training/[id]/+page.svelte`:

- Visible to session owner only
- Opens the adapted `ObsOverlayModal` in training mode

## Non-goals

- Leaderboard overlay for solo (single player, no value)
- Ghost paths in overlay (keep it simple, DAG only)
- Separate overlay modal component (reuse existing with mode prop)
