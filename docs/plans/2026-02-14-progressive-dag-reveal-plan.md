# Progressive DAG Reveal — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace binary show/hide DAG with fog-of-war progressive reveal showing discovered nodes + adjacent placeholders, for training and race participants.

**Architecture:** Server always sends full `graph_json` and `zone_history`. New `MetroDagProgressive` Svelte component computes visibility (discovered/adjacent/hidden) from `zone_history` and renders with fade-in transitions. Training and race pages wire it in based on context.

**Tech Stack:** Python/FastAPI (server), SvelteKit 5 with runes (frontend), SVG rendering

---

## Task 1: Server — Always include `zone_history`

Remove the `include_history` parameter from `participant_to_info()` and always include `zone_history`.

**Files:**

- Modify: `server/speedfog_racing/websocket/manager.py:181-207` (broadcast_leaderboard)
- Modify: `server/speedfog_racing/websocket/manager.py:249-275` (participant_to_info)
- Modify: `server/speedfog_racing/websocket/mod.py:488-492` (handle_finished caller)
- Modify: `server/speedfog_racing/websocket/spectator.py:139` (send_race_state caller)
- Modify: `server/speedfog_racing/websocket/spectator.py:223-232` (send_race_state function)
- Modify: `server/speedfog_racing/websocket/spectator.py:256-268` (broadcast_race_state_update)
- Modify: `server/speedfog_racing/websocket/training_spectator.py:151-172` (\_send_initial_state)
- Test: `server/tests/test_websocket.py`

### Step 1: Update `participant_to_info` — remove `include_history` param

In `server/speedfog_racing/websocket/manager.py`, change `participant_to_info()`:

```python
def participant_to_info(
    participant: Participant,
    *,
    connected_ids: set[uuid.UUID] | None = None,
    graph_json: dict[str, Any] | None = None,
) -> ParticipantInfo:
    """Convert a Participant model to ParticipantInfo schema."""
    # Compute tier on the fly from current_zone + graph_json
    tier: int | None = None
    if graph_json and participant.current_zone:
        tier = get_tier_for_node(participant.current_zone, graph_json)

    return ParticipantInfo(
        id=str(participant.id),
        twitch_username=participant.user.twitch_username,
        twitch_display_name=participant.user.twitch_display_name,
        status=participant.status.value,
        current_zone=participant.current_zone,
        current_layer=participant.current_layer,
        current_layer_tier=tier,
        igt_ms=participant.igt_ms,
        death_count=participant.death_count,
        color_index=participant.color_index,
        mod_connected=participant.id in connected_ids if connected_ids else False,
        zone_history=participant.zone_history,
    )
```

### Step 2: Update `broadcast_leaderboard` — remove `include_history` param

In `server/speedfog_racing/websocket/manager.py`, change `broadcast_leaderboard()`:

```python
async def broadcast_leaderboard(
    self,
    race_id: uuid.UUID,
    participants: list[Participant],
    *,
    graph_json: dict[str, Any] | None = None,
) -> None:
    """Broadcast leaderboard update to all connections in a room."""
    room = self.get_room(race_id)
    if not room:
        return

    sorted_participants = sort_leaderboard(participants)
    connected_ids = set(room.mods.keys())
    participant_infos = [
        participant_to_info(
            p,
            connected_ids=connected_ids,
            graph_json=graph_json,
        )
        for p in sorted_participants
    ]

    message = LeaderboardUpdateMessage(participants=participant_infos)
    await room.broadcast_to_all(message.model_dump_json())
```

### Step 3: Update callers — remove `include_history` arguments

In `server/speedfog_racing/websocket/mod.py:488-492`, change `handle_finished`:

```python
# Before:
await manager.broadcast_leaderboard(
    participant.race_id,
    participant.race.participants,
    include_history=all_finished,
    graph_json=_get_graph_json(participant),
)

# After:
await manager.broadcast_leaderboard(
    participant.race_id,
    participant.race.participants,
    graph_json=_get_graph_json(participant),
)
```

In `server/speedfog_racing/websocket/spectator.py:139`, change `handle_spectator_websocket`:

```python
# Before:
await send_race_state(
    websocket,
    race,
    dag_access=conn.dag_access,
    include_history=(race.status == RaceStatus.FINISHED),
)

# After:
await send_race_state(
    websocket,
    race,
    dag_access=conn.dag_access,
)
```

In `server/speedfog_racing/websocket/spectator.py:220-235`, update `send_race_state`:

```python
async def send_race_state(
    websocket: WebSocket,
    race: Race,
    *,
    dag_access: bool = False,
) -> None:
    """Send race state to spectator with appropriate DAG visibility."""
    room = manager.get_room(race.id)
    connected_ids = set(room.mods.keys()) if room else set()
    graph = race.seed.graph_json if race.seed else None
    sorted_participants = sort_leaderboard(race.participants)
    participant_infos: list[ParticipantInfo] = [
        participant_to_info(
            p, connected_ids=connected_ids, graph_json=graph
        )
        for p in sorted_participants
    ]

    message = RaceStateMessage(
        race=RaceInfo(
            id=str(race.id),
            name=race.name,
            status=race.status.value,
            started_at=race.started_at.isoformat() if race.started_at else None,
        ),
        seed=build_seed_info(race, dag_access),
        participants=participant_infos,
    )
    await websocket.send_text(message.model_dump_json())
```

In `server/speedfog_racing/websocket/spectator.py:256-268`, update `broadcast_race_state_update`:

```python
# Remove include_history variable and its usage — send_race_state no longer accepts it
include_history = race.status == RaceStatus.FINISHED  # DELETE this line

# The send_race_state call inside _send_to already handles it:
await asyncio.wait_for(
    send_race_state(
        conn.websocket,
        race,
        dag_access=dag_access,
    ),
    timeout=SEND_TIMEOUT,
)
```

In `server/speedfog_racing/websocket/training_spectator.py:151-172`, update `_send_initial_state`:

```python
# Before:
include_history = session.status == TrainingSessionStatus.FINISHED
...
zone_history=session.progress_nodes if include_history else None,

# After (just remove the conditional):
zone_history=session.progress_nodes,
```

### Step 4: Update tests

In `server/tests/test_websocket.py`, the existing `participant_to_info` tests don't pass `include_history`, so they should still pass. Add one test to verify zone_history is always included:

```python
def test_participant_info_always_includes_zone_history(self):
    """Test participant_to_info always includes zone_history."""
    user = MockUser(twitch_username="p1")
    history = [{"node_id": "node_a", "igt_ms": 1000}]
    participant = MockParticipant(user=user, zone_history=history)
    info = participant_to_info(participant)
    assert info.zone_history == history
```

### Step 5: Run tests

Run: `cd server && uv run pytest tests/test_websocket.py -v`
Expected: All pass, including the new test.

### Step 6: Commit

```bash
git add server/speedfog_racing/websocket/manager.py server/speedfog_racing/websocket/mod.py server/speedfog_racing/websocket/spectator.py server/speedfog_racing/websocket/training_spectator.py server/tests/test_websocket.py
git commit -m "feat(ws): always include zone_history in participant info"
```

---

## Task 2: Server — Always include `graph_json`

Remove the `dag_access` conditional from `build_seed_info()` so `graph_json` is always sent to all clients.

**Files:**

- Modify: `server/speedfog_racing/websocket/spectator.py:73-100` (build_seed_info)
- Modify: `server/speedfog_racing/websocket/schemas.py:85` (update comment)

### Step 1: Simplify `build_seed_info`

In `server/speedfog_racing/websocket/spectator.py`, replace `build_seed_info`:

```python
def build_seed_info(race: Race, dag_access: bool) -> SeedInfo:
    """Build SeedInfo — always includes graph_json for client-side filtering."""
    seed = race.seed
    if not seed:
        return SeedInfo(total_layers=0)

    graph_json = seed.graph_json or {}

    total_nodes = graph_json.get("total_nodes")
    if total_nodes is None:
        nodes = graph_json.get("nodes", {})
        total_nodes = len(nodes) if isinstance(nodes, dict) else 0

    total_paths = graph_json.get("total_paths", 0)

    return SeedInfo(
        total_layers=seed.total_layers,
        graph_json=seed.graph_json,
        total_nodes=total_nodes,
        total_paths=total_paths,
    )
```

Note: Keep the `dag_access` parameter in the signature for now to avoid changing all callers. It's just unused.

In `server/speedfog_racing/websocket/schemas.py:85`, update the comment:

```python
# Before:
graph_json: dict[str, object] | None = None  # Only for spectators

# After:
graph_json: dict[str, object] | None = None  # Full graph for client-side progressive reveal
```

### Step 2: Run tests

Run: `cd server && uv run pytest tests/ -v -x`
Expected: All pass.

### Step 3: Commit

```bash
git add server/speedfog_racing/websocket/spectator.py server/speedfog_racing/websocket/schemas.py
git commit -m "feat(ws): always send graph_json to all clients

Client-side progressive reveal replaces server-side DAG access filtering."
```

---

## Task 3: Frontend — Visibility utility function

Create a pure TypeScript utility that computes node/edge visibility from graph + discovered nodes. This is testable independently from the Svelte component.

**Files:**

- Create: `web/src/lib/dag/visibility.ts`

### Step 1: Create the visibility module

```typescript
/**
 * Progressive DAG visibility logic.
 *
 * Computes which nodes and edges are visible based on discovered node IDs.
 * Three states: discovered (full), adjacent (dim placeholder), hidden (not rendered).
 */

import type { DagNode, DagEdge, PositionedNode, RoutedEdge } from "./types";

export type NodeVisibility = "discovered" | "adjacent" | "hidden";

/**
 * Compute visibility for each node in the graph.
 *
 * - Discovered: node.id is in discoveredIds
 * - Adjacent: not discovered, but shares an edge with a discovered node
 * - Hidden: everything else
 * - The "start" node is always discovered
 */
export function computeNodeVisibility(
  nodes: DagNode[],
  edges: DagEdge[],
  discoveredIds: Set<string>,
): Map<string, NodeVisibility> {
  const result = new Map<string, NodeVisibility>();

  // Always include start node as discovered
  const effectiveDiscovered = new Set(discoveredIds);
  for (const node of nodes) {
    if (node.type === "start") {
      effectiveDiscovered.add(node.id);
    }
  }

  // Build adjacency from edges
  const neighbors = new Map<string, Set<string>>();
  for (const edge of edges) {
    if (!neighbors.has(edge.from)) neighbors.set(edge.from, new Set());
    if (!neighbors.has(edge.to)) neighbors.set(edge.to, new Set());
    neighbors.get(edge.from)!.add(edge.to);
    neighbors.get(edge.to)!.add(edge.from);
  }

  // Classify each node
  for (const node of nodes) {
    if (effectiveDiscovered.has(node.id)) {
      result.set(node.id, "discovered");
      continue;
    }

    // Check if any neighbor is discovered
    const nodeNeighbors = neighbors.get(node.id);
    if (nodeNeighbors) {
      for (const neighborId of nodeNeighbors) {
        if (effectiveDiscovered.has(neighborId)) {
          result.set(node.id, "adjacent");
          break;
        }
      }
    }

    if (!result.has(node.id)) {
      result.set(node.id, "hidden");
    }
  }

  return result;
}

/**
 * Filter positioned nodes to only those that are visible (discovered or adjacent).
 */
export function filterVisibleNodes(
  nodes: PositionedNode[],
  visibility: Map<string, NodeVisibility>,
): PositionedNode[] {
  return nodes.filter((n) => {
    const v = visibility.get(n.id);
    return v === "discovered" || v === "adjacent";
  });
}

/**
 * Filter edges to only those where both endpoints are visible.
 */
export function filterVisibleEdges(
  edges: RoutedEdge[],
  visibility: Map<string, NodeVisibility>,
): RoutedEdge[] {
  return edges.filter((e) => {
    const fromVis = visibility.get(e.fromId);
    const toVis = visibility.get(e.toId);
    return (
      (fromVis === "discovered" || fromVis === "adjacent") &&
      (toVis === "discovered" || toVis === "adjacent")
    );
  });
}

/**
 * Compute edge opacity based on endpoint visibility.
 * Both discovered: normal opacity. Any adjacent: dim.
 */
export function edgeOpacity(
  edge: RoutedEdge,
  visibility: Map<string, NodeVisibility>,
  normalOpacity: number,
): number {
  const fromVis = visibility.get(edge.fromId);
  const toVis = visibility.get(edge.toId);
  if (fromVis === "discovered" && toVis === "discovered") return normalOpacity;
  return 0.15;
}

/**
 * Extract discovered node IDs from a participant's zone_history.
 */
export function extractDiscoveredIds(
  zoneHistory: { node_id: string; igt_ms: number }[] | null,
  currentZone: string | null,
): Set<string> {
  const ids = new Set<string>();
  if (zoneHistory) {
    for (const entry of zoneHistory) {
      ids.add(entry.node_id);
    }
  }
  if (currentZone) {
    ids.add(currentZone);
  }
  return ids;
}
```

### Step 2: Export from index.ts

In `web/src/lib/dag/index.ts`, add:

```typescript
export {
  computeNodeVisibility,
  filterVisibleNodes,
  filterVisibleEdges,
  edgeOpacity,
  extractDiscoveredIds,
} from "./visibility";
export type { NodeVisibility } from "./visibility";
```

### Step 3: Commit

```bash
git add web/src/lib/dag/visibility.ts web/src/lib/dag/index.ts
git commit -m "feat(dag): add progressive visibility utility functions"
```

---

## Task 4: Frontend — `MetroDagProgressive` component

Create the new Svelte component that renders the DAG with fog-of-war visibility.

**Files:**

- Create: `web/src/lib/dag/MetroDagProgressive.svelte`
- Modify: `web/src/lib/dag/index.ts` (add export)
- Modify: `web/src/lib/dag/constants.ts` (add ADJACENT\_\* constants)

### Step 1: Add constants for adjacent node styling

In `web/src/lib/dag/constants.ts`, add at the end (before any closing export):

```typescript
// =============================================================================
// Progressive reveal (adjacent/undiscovered nodes)
// =============================================================================

export const ADJACENT_NODE_COLOR = "#444";
export const ADJACENT_OPACITY = 0.25;
export const ADJACENT_EDGE_OPACITY = 0.15;
export const REVEAL_TRANSITION_MS = 300;
```

### Step 2: Create `MetroDagProgressive.svelte`

Create `web/src/lib/dag/MetroDagProgressive.svelte`:

```svelte
<script lang="ts">
 import type { WsParticipant } from '$lib/websocket';
 import { parseDagGraph } from './types';
 import { computeLayout } from './layout';
 import {
  computeNodeVisibility,
  filterVisibleNodes,
  filterVisibleEdges,
  edgeOpacity,
  extractDiscoveredIds,
 } from './visibility';
 import {
  NODE_RADIUS,
  NODE_COLORS,
  BG_COLOR,
  EDGE_STROKE_WIDTH,
  EDGE_COLOR,
  EDGE_OPACITY,
  LABEL_MAX_CHARS,
  LABEL_FONT_SIZE,
  LABEL_COLOR,
  LABEL_OFFSET_Y,
  PLAYER_COLORS,
  RACER_DOT_RADIUS,
  ADJACENT_NODE_COLOR,
  ADJACENT_OPACITY,
  REVEAL_TRANSITION_MS,
 } from './constants';
 import type { PositionedNode, DagLayout, NodeVisibility } from './types';

 interface Props {
  graphJson: Record<string, unknown>;
  participants: WsParticipant[];
  myParticipantId: string;
 }

 let { graphJson, participants, myParticipantId }: Props = $props();

 // Full layout (stable positions regardless of visibility)
 let layout: DagLayout = $derived.by(() => {
  const graph = parseDagGraph(graphJson);
  return computeLayout(graph);
 });

 // Parse graph for edges (needed for adjacency computation)
 let graph = $derived(parseDagGraph(graphJson));

 // Extract discovered node IDs from my participant's zone_history
 let discoveredIds: Set<string> = $derived.by(() => {
  const me = participants.find((p) => p.id === myParticipantId);
  if (!me) return new Set<string>();
  return extractDiscoveredIds(me.zone_history, me.current_zone);
 });

 // Compute visibility for all nodes
 let visibility: Map<string, NodeVisibility> = $derived.by(() => {
  return computeNodeVisibility(graph.nodes, graph.edges, discoveredIds);
 });

 // Visible nodes and edges
 let visibleNodes: PositionedNode[] = $derived(filterVisibleNodes(layout.nodes, visibility));
 let visibleEdges = $derived(filterVisibleEdges(layout.edges, visibility));

 // Node ID lookup for player dot positioning
 let nodeById = $derived.by(() => {
  const map = new Map<string, PositionedNode>();
  for (const node of layout.nodes) {
   map.set(node.id, node);
  }
  return map;
 });

 // Player dot (only for my participant, only on discovered nodes)
 let playerDot = $derived.by(() => {
  const me = participants.find((p) => p.id === myParticipantId);
  if (!me || !me.current_zone) return null;
  if (me.status !== 'playing' && me.status !== 'finished') return null;
  if (visibility.get(me.current_zone) !== 'discovered') return null;

  const node = nodeById.get(me.current_zone);
  if (!node) return null;

  return {
   x: node.x,
   y: node.y,
   color: PLAYER_COLORS[me.color_index % PLAYER_COLORS.length],
   displayName: me.twitch_display_name || me.twitch_username,
  };
 });

 // Label placement (same logic as MetroDagLive)
 let labelAbove: Set<string> = $derived.by(() => {
  const above = new Set<string>();
  const byLayer = new Map<number, PositionedNode[]>();
  for (const node of layout.nodes) {
   const list = byLayer.get(node.layer);
   if (list) list.push(node);
   else byLayer.set(node.layer, [node]);
  }
  for (const nodes of byLayer.values()) {
   if (nodes.length < 2) continue;
   const top = nodes.reduce((a, b) => (a.y < b.y ? a : b));
   above.add(top.id);
  }
  return above;
 });

 function truncateLabel(name: string): string {
  const short = name.includes(' - ') ? name.split(' - ').pop()! : name;
  if (short.length <= LABEL_MAX_CHARS) return short;
  return short.slice(0, LABEL_MAX_CHARS - 1) + '\u2026';
 }

 function nodeRadius(node: PositionedNode): number {
  return NODE_RADIUS[node.type];
 }

 function nodeColor(node: PositionedNode): string {
  const vis = visibility.get(node.id);
  return vis === 'discovered' ? NODE_COLORS[node.type] : ADJACENT_NODE_COLOR;
 }

 function nodeOpacity(node: PositionedNode): number {
  return visibility.get(node.id) === 'discovered' ? 1.0 : ADJACENT_OPACITY;
 }

 function isDiscovered(node: PositionedNode): boolean {
  return visibility.get(node.id) === 'discovered';
 }

 function labelX(node: PositionedNode): number {
  if (labelAbove.has(node.id)) return node.x;
  return node.x - 6;
 }

 function labelY(node: PositionedNode): number {
  const r = nodeRadius(node);
  if (labelAbove.has(node.id)) {
   return node.y - r - 8;
  }
  return node.y + r + LABEL_OFFSET_Y - 6;
 }

 let transitionStyle = `transition: opacity ${REVEAL_TRANSITION_MS}ms ease`;
</script>

<div class="metro-dag-container">
 {#if layout.nodes.length > 0}
  <svg
   viewBox="0 0 {layout.width} {layout.height}"
   width="100%"
   preserveAspectRatio="xMidYMid meet"
   class="metro-dag-svg"
  >
   <defs>
    <filter id="player-glow-prog" x="-50%" y="-50%" width="200%" height="200%">
     <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
     <feMerge>
      <feMergeNode in="blur" />
      <feMergeNode in="SourceGraphic" />
     </feMerge>
    </filter>
   </defs>

   <!-- Edges -->
   {#each visibleEdges as edge (edge.fromId + '-' + edge.toId)}
    <g style={transitionStyle} opacity={edgeOpacity(edge, visibility, EDGE_OPACITY)}>
     {#each edge.segments as seg}
      <line
       x1={seg.x1}
       y1={seg.y1}
       x2={seg.x2}
       y2={seg.y2}
       stroke={EDGE_COLOR}
       stroke-width={EDGE_STROKE_WIDTH}
       stroke-linecap="round"
      />
     {/each}
    </g>
   {/each}

   <!-- Nodes -->
   {#each visibleNodes as node (node.id)}
    <g
     class="dag-node"
     data-type={node.type}
     style={transitionStyle}
     opacity={nodeOpacity(node)}
    >
     <title>{isDiscovered(node) ? node.displayName : '???'}</title>

     <g class="dag-node-shape">
      {#if node.type === 'start'}
       <circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
       {#if isDiscovered(node)}
        <polygon
         points="{node.x - 3},{node.y - 5} {node.x - 3},{node.y + 5} {node.x + 5},{node.y}"
         fill={BG_COLOR}
        />
       {/if}
      {:else if node.type === 'final_boss'}
       <circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
       {#if isDiscovered(node)}
        <rect x={node.x - 4} y={node.y - 4} width="8" height="8" fill={BG_COLOR} />
       {/if}
      {:else if node.type === 'mini_dungeon'}
       <circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
      {:else if node.type === 'boss_arena'}
       {#if isDiscovered(node)}
        <circle
         cx={node.x}
         cy={node.y}
         r={nodeRadius(node)}
         fill={BG_COLOR}
         stroke={nodeColor(node)}
         stroke-width="3"
        />
       {:else}
        <circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
       {/if}
      {:else if node.type === 'major_boss'}
       {#if isDiscovered(node)}
        <rect
         x={node.x - nodeRadius(node) * 0.7}
         y={node.y - nodeRadius(node) * 0.7}
         width={nodeRadius(node) * 1.4}
         height={nodeRadius(node) * 1.4}
         fill={nodeColor(node)}
         transform="rotate(45 {node.x} {node.y})"
        />
       {:else}
        <circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
       {/if}
      {:else if node.type === 'legacy_dungeon'}
       {#if isDiscovered(node)}
        <circle
         cx={node.x}
         cy={node.y}
         r={nodeRadius(node)}
         fill="none"
         stroke={nodeColor(node)}
         stroke-width="3"
        />
        <circle cx={node.x} cy={node.y} r={nodeRadius(node) * 0.5} fill={nodeColor(node)} />
       {:else}
        <circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
       {/if}
      {/if}
     </g>

     <!-- Label (only for discovered nodes) -->
     {#if isDiscovered(node)}
      <text
       x={labelX(node)}
       y={labelY(node)}
       text-anchor={labelAbove.has(node.id) ? 'start' : 'end'}
       font-size={LABEL_FONT_SIZE}
       fill={LABEL_COLOR}
       class="dag-label"
       transform="rotate(-30, {labelX(node)}, {labelY(node)})"
      >
       {truncateLabel(node.displayName)}
      </text>
     {/if}
    </g>
   {/each}

   <!-- Player dot -->
   {#if playerDot}
    <circle
     cx={playerDot.x}
     cy={playerDot.y}
     r={RACER_DOT_RADIUS}
     fill={playerDot.color}
     filter="url(#player-glow-prog)"
     class="player-dot"
    >
     <title>{playerDot.displayName}</title>
    </circle>
   {/if}
  </svg>
 {/if}
</div>

<style>
 .metro-dag-container {
  width: 100%;
  overflow-x: auto;
  background: var(--color-surface, #1a1a2e);
  border-radius: var(--radius-lg, 8px);
  min-height: 200px;
  display: flex;
  align-items: center;
  justify-content: center;
 }

 .metro-dag-svg {
  display: block;
  min-width: 600px;
 }

 .dag-label {
  pointer-events: none;
  user-select: none;
  font-family:
   system-ui,
   -apple-system,
   sans-serif;
  paint-order: stroke;
  stroke: var(--color-surface, #1a1a2e);
  stroke-width: 4px;
  stroke-linejoin: round;
 }

 .dag-node {
  cursor: pointer;
 }

 .dag-node-shape {
  transform-box: fill-box;
  transform-origin: center;
  transition: transform 0.15s ease;
 }

 .dag-node:hover .dag-node-shape {
  transform: scale(1.3);
 }

 .player-dot {
  transition:
   cx 0.3s ease,
   cy 0.3s ease;
 }
</style>
```

### Step 3: Add export to index.ts

In `web/src/lib/dag/index.ts`, add after the MetroDagResults export:

```typescript
export { default as MetroDagProgressive } from "./MetroDagProgressive.svelte";
```

### Step 4: Run type check

Run: `cd web && npm run check`
Expected: No new errors.

### Step 5: Commit

```bash
git add web/src/lib/dag/MetroDagProgressive.svelte web/src/lib/dag/index.ts web/src/lib/dag/constants.ts
git commit -m "feat(dag): add MetroDagProgressive component

Fog-of-war DAG showing discovered nodes (full), adjacent nodes
(dim placeholders), and hiding everything else. Fade-in on reveal."
```

---

## Task 5: Training page integration

Replace the binary show/hide with progressive DAG by default, "Show Spoiler" toggles to full view.

**Files:**

- Modify: `web/src/routes/training/[id]/+page.svelte`

### Step 1: Update the training page

In `web/src/routes/training/[id]/+page.svelte`:

1. Add import for `MetroDagProgressive`:

```typescript
import {
  MetroDag,
  MetroDagLive,
  MetroDagProgressive,
  MetroDagResults,
} from "$lib/dag";
```

1. Change `showDag` to `showFullDag` (default false):

```typescript
let showFullDag = $state(false);
```

1. Remove auto-show logic in `loadSession`:

```typescript
// DELETE: if (session.status === 'finished') { showDag = true; }
```

1. Replace the DAG section template:

```svelte
<!-- DAG section -->
{#if graphJson}
 <section class="dag-section">
  {#if status === 'finished' && dagParticipants.length > 0}
   <MetroDagResults {graphJson} participants={dagParticipants} />
  {:else if status === 'active' && dagParticipants.length > 0}
   <button class="btn btn-secondary btn-sm" onclick={() => (showFullDag = !showFullDag)}>
    {showFullDag ? 'Hide Spoiler' : 'Show Spoiler'}
   </button>
   <div class="dag-wrapper">
    {#if showFullDag}
     <MetroDagLive {graphJson} participants={dagParticipants} />
    {:else}
     <MetroDagProgressive
      {graphJson}
      participants={dagParticipants}
      myParticipantId={liveParticipant?.id ?? ''}
     />
    {/if}
   </div>
  {:else}
   <MetroDag {graphJson} />
  {/if}
 </section>
{/if}
```

Key changes:

- Progressive DAG visible by default during active sessions (no click needed)
- "Show Spoiler" button toggles between progressive and full MetroDagLive
- Finished: MetroDagResults shown directly (no toggle)

### Step 2: Run type check

Run: `cd web && npm run check`
Expected: No new errors.

### Step 3: Commit

```bash
git add web/src/routes/training/[id]/+page.svelte
git commit -m "feat(training): show progressive DAG by default

Progressive reveal visible immediately during active training.
'Show Spoiler' toggles to full DAG view."
```

---

## Task 6: Race page integration

Show progressive DAG for race participants instead of nothing.

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`

### Step 1: Add import and participant ID derivation

In `web/src/routes/race/[id]/+page.svelte`:

1. Add import:

```typescript
import {
  MetroDag,
  MetroDagBlurred,
  MetroDagLive,
  MetroDagProgressive,
  MetroDagResults,
} from "$lib/dag";
```

1. Derive the current user's participant ID from the WS participants list. Add after `myParticipant`:

```typescript
let myWsParticipantId = $derived.by(() => {
  if (!myParticipant) return null;
  // Match REST participant to WS participant by username
  const wsP = raceStore.participants.find(
    (p) => p.twitch_username === myParticipant.user.twitch_username,
  );
  return wsP?.id ?? null;
});
```

1. Update the DAG rendering section (lines 288-306) to include progressive mode:

```svelte
{#if liveSeed?.graph_json && raceStatus === 'running'}
 {#if myWsParticipantId}
  <MetroDagProgressive
   graphJson={liveSeed.graph_json}
   participants={raceStore.participants}
   myParticipantId={myWsParticipantId}
  />
 {:else}
  <MetroDagLive graphJson={liveSeed.graph_json} participants={raceStore.participants} />
 {/if}
{:else if liveSeed?.graph_json && raceStatus === 'finished'}
 <Podium participants={raceStore.leaderboard} />
 <MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} />
 <RaceStats participants={raceStore.leaderboard} />
{:else if liveSeed?.graph_json}
 <MetroDag graphJson={liveSeed.graph_json} />
{:else if totalNodes && totalPaths && totalLayers}
 <MetroDagBlurred
  {totalLayers}
  {totalNodes}
  {totalPaths}
 />
{:else if totalLayers}
 <div class="dag-placeholder">
  <p class="dag-note">DAG hidden until race starts</p>
 </div>
{/if}
```

Logic: If the current user is a participant (`myWsParticipantId` is non-null) and the race is running, show `MetroDagProgressive`. Otherwise, show `MetroDagLive` for spectators.

### Step 2: Run type check

Run: `cd web && npm run check`
Expected: No new errors.

### Step 3: Commit

```bash
git add web/src/routes/race/[id]/+page.svelte
git commit -m "feat(race): show progressive DAG for participants

Race participants see fog-of-war DAG during running races instead
of no DAG. Spectators still see the full live DAG."
```

---

## Task 7: Cleanup — Remove dead code

The `dag_access` field on `SpectatorConnection` and parts of `compute_dag_access` are now unused for graph filtering. Clean up.

**Files:**

- Modify: `server/speedfog_racing/websocket/spectator.py`
- Modify: `server/speedfog_racing/websocket/manager.py`

### Step 1: Simplify `build_seed_info` — remove unused `dag_access` param

```python
def build_seed_info(race: Race) -> SeedInfo:
    """Build SeedInfo — always includes graph_json for client-side filtering."""
    seed = race.seed
    if not seed:
        return SeedInfo(total_layers=0)

    graph_json = seed.graph_json or {}

    total_nodes = graph_json.get("total_nodes")
    if total_nodes is None:
        nodes = graph_json.get("nodes", {})
        total_nodes = len(nodes) if isinstance(nodes, dict) else 0

    total_paths = graph_json.get("total_paths", 0)

    return SeedInfo(
        total_layers=seed.total_layers,
        graph_json=seed.graph_json,
        total_nodes=total_nodes,
        total_paths=total_paths,
    )
```

### Step 2: Update all callers of `build_seed_info`

Replace `build_seed_info(race, dag_access)` → `build_seed_info(race)` and `build_seed_info(race, conn.dag_access)` → `build_seed_info(race)`.

### Step 3: Remove `dag_access` from `SpectatorConnection`

In `manager.py`, remove the `dag_access: bool = False` field from `SpectatorConnection`.

### Step 4: Remove `conn.dag_access` assignments in `spectator.py`

Delete lines like `conn.dag_access = compute_dag_access(user_id, race)` and `conn.dag_access = dag_access`.

### Step 5: Remove `send_race_state` `dag_access` parameter

Update `send_race_state` to no longer accept `dag_access`:

```python
async def send_race_state(
    websocket: WebSocket,
    race: Race,
) -> None:
```

And update its callers.

### Step 6: Keep `compute_dag_access` for now

`compute_dag_access` may still be useful for future features (e.g., restricting spectator features). Leave it in place but remove its usage from the graph filtering path. Add a comment:

```python
# NOTE: compute_dag_access is retained for potential future use (e.g., restricting
# spectator features beyond graph visibility). Currently unused after progressive
# DAG reveal moved filtering to the client.
```

### Step 7: Run full test suite

Run: `cd server && uv run pytest tests/ -v`
Expected: All pass.

### Step 8: Commit

```bash
git add server/speedfog_racing/websocket/spectator.py server/speedfog_racing/websocket/manager.py
git commit -m "refactor(ws): remove dag_access plumbing from spectator flow

Progressive DAG reveal is fully client-side. Server no longer needs
to track per-connection DAG access for graph filtering."
```

---

## Task 8: Manual smoke test

Verify the feature works end-to-end by visual inspection.

### Step 1: Start dev servers

Run server: `cd server && uv run speedfog-racing`
Run frontend: `cd web && npm run dev`

### Step 2: Training smoke test

1. Create a training session
1. Open the training session page
1. Verify: progressive DAG shows start node + adjacent nodes
1. Verify: "Show Spoiler" toggles to full DAG
1. Verify: finishing shows MetroDagResults

### Step 3: Race smoke test (if possible)

1. Create a race, add a participant
1. Open race page as participant
1. Verify: during running, participant sees progressive DAG
1. Open race page as spectator in another browser/incognito
1. Verify: spectator sees full MetroDagLive

### Step 4: Commit plan doc update

```bash
git add docs/plans/2026-02-14-progressive-dag-reveal-plan.md
git commit -m "docs: add progressive DAG reveal implementation plan"
```
