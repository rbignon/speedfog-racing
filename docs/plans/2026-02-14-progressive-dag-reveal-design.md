# Progressive DAG Reveal

**Date:** 2026-02-14
**Status:** Approved

## Summary

Replace the binary show/hide DAG behavior with a progressive reveal: only nodes the player has discovered (via event flags) are visible, plus adjacent undiscovered nodes shown as dim placeholders. Applies to training mode and race participants.

## Context

Currently:

- Training (active): DAG hidden by default, "Show Spoiler" reveals the full graph
- Race participants (running): no DAG at all (`graph_json=None`)
- Spectators/casters: full DAG always visible

The progressive reveal gives players a "fog of war" view of their seed graph without spoiling upcoming content.

## Design Decisions

- **Client-side filtering.** Server sends full `graph_json` to everyone. Filtering happens in the frontend. Trust-based approach — a player who wants to cheat can just disconnect from the site.
- **Spectators always see the full DAG.** Progressive reveal only affects the player's own view.
- **Fade-in animation.** Newly revealed nodes and edges fade in over ~300ms via CSS transitions.

## Server Changes

### 1. Always send `graph_json`

In `build_seed_info()` (spectator.py), remove the `dag_access` conditional. The `graph_json` field is always populated regardless of viewer role.

### 2. Always send `zone_history`

In `participant_to_info()` (manager.py), remove the `include_history` parameter. `zone_history` is always included in WS messages (`leaderboard_update`, `race_state`, `player_update`).

Bandwidth cost: ~50-100 bytes per discovered node, ~2-4 KB max per participant for a complete run. Negligible for 8 participants.

No new WS message types or endpoints.

## Visibility Logic

Three node states derived from `discoveredNodeIds: Set<string>` (extracted from `zone_history`):

| State          | Condition                                             | Rendering                                      |
| -------------- | ----------------------------------------------------- | ---------------------------------------------- |
| **Discovered** | `node.id in discoveredNodeIds`                        | Full shape, color, label                       |
| **Adjacent**   | Not discovered, shares an edge with a discovered node | Grey silhouette (#444), no label, opacity 0.25 |
| **Hidden**     | Everything else                                       | Not rendered                                   |

Special cases:

- The `start` node is always discovered
- An edge is visible if both endpoints are visible (discovered or adjacent)
- An edge between two discovered nodes renders normally; an edge involving an adjacent node renders at opacity 0.15
- Player dot renders on `current_zone` only if the node is discovered

## New Component: `MetroDagProgressive`

File: `web/src/lib/dag/MetroDagProgressive.svelte`

```typescript
interface Props {
  graphJson: Record<string, unknown>;
  participants: WsParticipant[];
  myParticipantId: string;
}
```

Internal flow:

1. Parse `graphJson` and `computeLayout()` — stable positions (same as MetroDagLive)
2. Derive `discoveredNodeIds` from the participant matching `myParticipantId`
3. Derive `adjacentNodeIds` from graph edges (direct neighbors of discovered nodes)
4. Derive `visibleEdges` (both endpoints are discovered or adjacent)
5. Render SVG with visibility classes and CSS transitions for fade-in

## Page Integration

### Training (`/training/[id]/+page.svelte`)

- **Active:** `MetroDagProgressive` visible by default (no click needed)
- **"Show Spoiler" button:** toggles between progressive and full `MetroDagLive`
- **Finished:** `MetroDagResults` (unchanged)

### Race (`/race/[id]/+page.svelte`)

- **Running, participant:** `MetroDagProgressive` (replaces "no DAG")
- **Running, spectator/caster:** `MetroDagLive` (unchanged)
- **Finished:** `MetroDagResults` (unchanged)

### Unchanged Components

- `MetroDag` (static preview)
- `MetroDagResults` (finished results)
- `MetroDagBlurred` (draft/open placeholder)
- `MetroDagAnimated` (homepage hero)
