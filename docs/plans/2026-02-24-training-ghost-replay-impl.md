# Training Ghost Replay Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a ghost replay to `/training/:id` that animates the player's run alongside anonymous ghosts (all other finished training sessions on the same seed).

**Architecture:** New API endpoint returns ghost zone histories for a given training session. Frontend fetches ghosts, maps them to `WsParticipant[]` with gray colors, and feeds them into the existing `RaceReplay` engine. `ReplayDag` is extended to support per-participant opacity (dots + skulls) for ghost differentiation.

**Tech Stack:** Python/FastAPI (server), SvelteKit 5 with runes (frontend), existing replay engine (`timeline.ts`, `ReplayDag`, `ReplayControls`)

---

## Task 1: Ghost API Endpoint

**Files:**

- Modify: `server/speedfog_racing/schemas.py`
- Modify: `server/speedfog_racing/api/training.py`
- Modify: `server/tests/test_training.py`

### Step 1: Write the failing test

Add to the end of `server/tests/test_training.py`:

```python
# =============================================================================
# Ghost replay endpoint
# =============================================================================


@pytest.mark.asyncio
async def test_ghost_endpoint_returns_finished_sessions(async_session, training_user, training_seed, monkeypatch):
    """GET /api/training/{id}/ghosts returns zone_history of other finished sessions on the same seed."""
    monkeypatch.setattr(
        "speedfog_racing.api.training.get_pool_config",
        lambda name: {"type": "training", "display": {"label": name}},
    )

    # Create the "current" session (finished)
    async with async_session() as db:
        current = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
            status=TrainingSessionStatus.FINISHED,
            igt_ms=300000,
            death_count=5,
            progress_nodes=[
                {"node_id": "limgrave_start", "igt_ms": 0, "deaths": 0},
                {"node_id": "stormveil_01", "igt_ms": 150000, "deaths": 5},
            ],
        )
        db.add(current)
        await db.commit()
        await db.refresh(current)
        current_id = current.id

    # Create a second user with two finished sessions on same seed
    async with async_session() as db:
        ghost_user = User(
            twitch_id="ghost_user_1",
            twitch_username="ghostrunner",
            api_token=generate_token(),
            role=UserRole.USER,
        )
        db.add(ghost_user)
        await db.commit()
        await db.refresh(ghost_user)

        ghost1 = TrainingSession(
            user_id=ghost_user.id,
            seed_id=training_seed.id,
            status=TrainingSessionStatus.FINISHED,
            igt_ms=250000,
            death_count=3,
            progress_nodes=[
                {"node_id": "limgrave_start", "igt_ms": 0, "deaths": 1},
                {"node_id": "stormveil_01", "igt_ms": 120000, "deaths": 2},
            ],
        )
        # Also create an ACTIVE session — should NOT appear in ghosts
        ghost2_active = TrainingSession(
            user_id=ghost_user.id,
            seed_id=training_seed.id,
            status=TrainingSessionStatus.ACTIVE,
            igt_ms=50000,
            progress_nodes=[{"node_id": "limgrave_start", "igt_ms": 0}],
        )
        db.add_all([ghost1, ghost2_active])
        await db.commit()

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/training/{current_id}/ghosts")

    assert resp.status_code == 200
    ghosts = resp.json()
    assert len(ghosts) == 1  # Only the finished ghost, not the active one, not self
    assert ghosts[0]["igt_ms"] == 250000
    assert ghosts[0]["death_count"] == 3
    assert len(ghosts[0]["zone_history"]) == 2


@pytest.mark.asyncio
async def test_ghost_endpoint_excludes_self(async_session, training_user, training_seed, monkeypatch):
    """The current session should not appear in its own ghost list."""
    monkeypatch.setattr(
        "speedfog_racing.api.training.get_pool_config",
        lambda name: {"type": "training", "display": {"label": name}},
    )

    async with async_session() as db:
        session = TrainingSession(
            user_id=training_user.id,
            seed_id=training_seed.id,
            status=TrainingSessionStatus.FINISHED,
            igt_ms=300000,
            progress_nodes=[{"node_id": "limgrave_start", "igt_ms": 0}],
        )
        db.add(session)
        await db.commit()
        await db.refresh(session)
        session_id = session.id

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/training/{session_id}/ghosts")

    assert resp.status_code == 200
    assert resp.json() == []


@pytest.mark.asyncio
async def test_ghost_endpoint_404_for_missing_session(async_session, monkeypatch):
    """Returns 404 for non-existent session."""
    monkeypatch.setattr(
        "speedfog_racing.api.training.get_pool_config",
        lambda name: {"type": "training", "display": {"label": name}},
    )

    import uuid

    from httpx import ASGITransport, AsyncClient

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        resp = await ac.get(f"/api/training/{uuid.uuid4()}/ghosts")

    assert resp.status_code == 404
```

### Step 2: Run tests to verify they fail

Run: `cd server && uv run pytest tests/test_training.py -k "ghost" -v`
Expected: FAIL — endpoint does not exist yet (404 from FastAPI, not our 404)

### Step 3: Add the ghost response schema

In `server/speedfog_racing/schemas.py`, add at the end (before any final blank lines):

```python
class GhostResponse(BaseModel):
    """Anonymous ghost data for replay."""

    zone_history: list[dict[str, Any]]
    igt_ms: int
    death_count: int
```

Also add `from typing import Any` to the imports if not already present.

### Step 4: Implement the ghost endpoint

In `server/speedfog_racing/api/training.py`:

Add `GhostResponse` to the imports from `speedfog_racing.schemas`.

Add `Seed` to the imports from `speedfog_racing.models`.

Add this endpoint at the end of the file (before any trailing blank line):

```python
@router.get("/{session_id}/ghosts", response_model=list[GhostResponse])
async def get_ghosts(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
) -> list[GhostResponse]:
    """Get anonymous ghost data for all finished training sessions on the same seed."""
    # Load the target session to get its seed_id
    result = await db.execute(
        select(TrainingSession).where(TrainingSession.id == session_id)
    )
    session = result.scalar_one_or_none()
    if not session:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Solo session not found")

    # Find all other finished sessions on the same seed
    result = await db.execute(
        select(TrainingSession).where(
            TrainingSession.seed_id == session.seed_id,
            TrainingSession.status == TrainingSessionStatus.FINISHED,
            TrainingSession.id != session_id,
            TrainingSession.progress_nodes.isnot(None),
        )
    )
    ghosts = list(result.scalars().all())

    return [
        GhostResponse(
            zone_history=g.progress_nodes or [],
            igt_ms=g.igt_ms,
            death_count=g.death_count,
        )
        for g in ghosts
    ]
```

### Step 5: Run tests to verify they pass

Run: `cd server && uv run pytest tests/test_training.py -k "ghost" -v`
Expected: 3 tests PASS

### Step 6: Run full server test suite and linting

Run: `cd server && uv run pytest -x -q`
Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`

### Step 7: Commit

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/training.py server/tests/test_training.py
git commit -m "feat(api): add ghost endpoint for training replay"
```

---

## Task 2: Frontend API Client + Ghost Fetching

**Files:**

- Modify: `web/src/lib/api.ts`

### Step 1: Add ghost types and fetch function

In `web/src/lib/api.ts`, add the ghost type and fetch function near the other training functions (around line 1017):

```typescript
export interface Ghost {
  zone_history: Array<{ node_id: string; igt_ms: number; deaths?: number }>;
  igt_ms: number;
  death_count: number;
}

export async function fetchTrainingGhosts(sessionId: string): Promise<Ghost[]> {
  const res = await fetch(`/api/training/${sessionId}/ghosts`);
  if (!res.ok) return [];
  return res.json();
}
```

### Step 2: Run type checking

Run: `cd web && npm run check`
Expected: PASS

### Step 3: Commit

```bash
git add web/src/lib/api.ts
git commit -m "feat(web): add ghost API client for training replay"
```

---

## Task 3: Extend ReplayDag for Ghost Styling

The replay engine needs to differentiate the current player from ghosts. The cleanest approach: add an optional `ghostIds` set to `ReplayDag` that controls dot opacity and skull opacity.

**Files:**

- Modify: `web/src/lib/replay/ReplayDag.svelte`

### Step 1: Add ghostIds prop

In `web/src/lib/replay/ReplayDag.svelte`, extend the Props interface (line 7-21):

```typescript
interface Props {
  /** Current race IGT in the replay */
  currentIgt: number;
  /** Wall-clock elapsed replay time (for orbit animation) */
  replayElapsedMs: number;
  maxIgt: number;
  replayParticipants: ReplayParticipant[];
  skullEvents: SkullEvent[];
  nodePositions: Map<string, { x: number; y: number }>;
  nodeInfo: Map<string, { layer: number; type: string }>;
  leaderId: string | null;
  previousLeader: string | null;
  /** Callback when leader changes */
  onleaderchange: (newLeaderId: string | null) => void;
  /** IDs of ghost participants (rendered with reduced opacity) */
  ghostIds?: Set<string>;
}
```

Update the destructuring (line 23-34) to include `ghostIds`:

```typescript
let {
  currentIgt,
  replayElapsedMs,
  maxIgt,
  replayParticipants,
  skullEvents,
  nodePositions,
  nodeInfo,
  leaderId,
  previousLeader,
  onleaderchange,
  ghostIds,
}: Props = $props();
```

### Step 2: Apply ghost styling to player dots

In the player dots section (around line 127-153), update the rendering to apply ghost opacity:

Replace the player dots block:

```svelte
<!-- Player dots -->
{#each snapshots as snap (snap.participantId)}
 {@const rp = replayParticipants.find((r) => r.id === snap.participantId)}
 {@const isGhost = ghostIds?.has(snap.participantId) ?? false}
 {#if rp}
  <circle
   cx={snap.x}
   cy={snap.y}
   r={RACER_DOT_RADIUS}
   fill={rp.color}
   opacity={isGhost ? 0.5 : 1}
   class="replay-dot"
   filter={isGhost ? undefined : 'url(#replay-player-glow)'}
  >
   <title>{rp.displayName}</title>
  </circle>
  <!-- Leader star (never on ghosts) -->
  {#if snap.participantId === leaderId && !isGhost}
   <text
    x={snap.x}
    y={snap.y - RACER_DOT_RADIUS - 5}
    text-anchor="middle"
    font-size="14"
    fill={leaderChanged ? '#FACC15' : '#C8A44E'}
    class="leader-star"
    class:flash={leaderChanged}
   >&#x2B51;</text>
  {/if}
 {/if}
{/each}
```

### Step 3: Apply ghost styling to skulls

Replace the skull animations block (around line 155-169):

```svelte
<!-- Skull animations -->
{#each activeSkulls as skull}
 {@const pos = nodePositions.get(skull.nodeId)}
 {@const isGhostSkull = ghostIds?.has(skull.participantId) ?? false}
 {#if pos}
  <text
   x={pos.x}
   y={pos.y}
   text-anchor="middle"
   dominant-baseline="central"
   font-size={18 * skullScale(skull.progress)}
   opacity={(isGhostSkull ? 0.3 : 1) * skullOpacity(skull.progress)}
   class="skull-anim"
  >&#x1F480;</text>
 {/if}
{/each}
```

### Step 4: Run type checking

Run: `cd web && npm run check`
Expected: PASS (ghostIds is optional, so existing RaceReplay usage is unchanged)

### Step 5: Commit

```bash
git add web/src/lib/replay/ReplayDag.svelte
git commit -m "feat(replay): add ghost styling support to ReplayDag"
```

---

## Task 4: Add Ghost Counter to ReplayControls

**Files:**

- Modify: `web/src/lib/replay/ReplayControls.svelte`

### Step 1: Add ghostCount prop

Extend the Props interface in `ReplayControls.svelte`:

```typescript
interface Props {
  replayState: ReplayState;
  /** Current position in replay, 0–1 */
  progress: number;
  /** Current playback speed multiplier */
  speed: number;
  onplay: () => void;
  onpause: () => void;
  onseek: (progress: number) => void;
  onspeed: (speed: number) => void;
  /** Number of ghost players in the replay (optional, training mode) */
  ghostCount?: number;
}
```

Update the destructuring to include `ghostCount`.

### Step 2: Render ghost counter

After the speed selector in the template (after the `<div class="speed-selector">...</div>`, around line 93), add:

```svelte
{#if ghostCount != null && ghostCount > 0}
 <span class="ghost-count">{ghostCount} ghost{ghostCount !== 1 ? 's' : ''}</span>
{/if}
```

### Step 3: Add ghost counter styles

In the `<style>` block, add:

```css
.ghost-count {
  font-size: var(--font-size-xs);
  color: var(--color-text-disabled);
  margin-left: auto;
  white-space: nowrap;
}
```

### Step 4: Run type checking

Run: `cd web && npm run check`
Expected: PASS

### Step 5: Commit

```bash
git add web/src/lib/replay/ReplayControls.svelte
git commit -m "feat(replay): add ghost counter to ReplayControls"
```

---

## Task 5: Integrate Ghost Replay into Training Detail Page

**Files:**

- Modify: `web/src/routes/training/[id]/+page.svelte`

### Step 1: Add imports and ghost state

At the top of the `<script>` block, add the new imports:

```typescript
import { fetchTrainingGhosts, type Ghost } from "$lib/api";
import RaceReplay from "$lib/replay/RaceReplay.svelte";
```

Wait — `RaceReplay` currently hardcodes `participants.length >= 2` check (line 192). And it doesn't accept `ghostIds`. We need a different approach.

Actually, looking at the design: we should NOT reuse `RaceReplay` directly because:

1. It requires `>=2` participants (line 192)
2. It has commentary/highlights logic we don't want
3. It doesn't pass `ghostIds` to `ReplayDag`

Better approach: Create a lightweight `TrainingReplay.svelte` that reuses `ReplayDag`, `ReplayControls`, `ZoomableSvg`, `DagBaseLayer`, and `timeline.ts` directly (like `RaceReplay` does), but without commentary/highlights and with ghost support.

### Step 1 (revised): Create TrainingReplay component

Create `web/src/lib/replay/TrainingReplay.svelte`:

```svelte
<script lang="ts">
 import type { WsParticipant } from '$lib/websocket';
 import type { ReplayState } from './types';
 import { REPLAY_DEFAULTS } from './types';
 import { buildReplayParticipants, collectSkullEvents, replayMsToIgt } from './timeline';
 import { PLAYER_COLORS } from '$lib/dag/constants';
 import { parseDagGraph } from '$lib/dag/types';
 import { computeLayout } from '$lib/dag/layout';
 import type { PositionedNode } from '$lib/dag/types';
 import ZoomableSvg from '$lib/dag/ZoomableSvg.svelte';
 import DagBaseLayer from '$lib/dag/DagBaseLayer.svelte';
 import ReplayDag from './ReplayDag.svelte';
 import ReplayControls from './ReplayControls.svelte';

 interface Props {
  graphJson: Record<string, unknown>;
  /** The current player as a WsParticipant */
  currentPlayer: WsParticipant;
  /** Ghost participants (anonymous, will be rendered gray) */
  ghosts: WsParticipant[];
 }

 let { graphJson, currentPlayer, ghosts }: Props = $props();

 // Ensure current player gets a real color, ghosts get gray
 let allParticipants = $derived([currentPlayer, ...ghosts]);

 // Pre-compute layout
 let graph = $derived(parseDagGraph(graphJson));
 let layout = $derived(computeLayout(graph));

 let nodePositions = $derived.by(() => {
  const map = new Map<string, { x: number; y: number }>();
  for (const node of layout.nodes) {
   map.set(node.id, { x: node.x, y: node.y });
  }
  return map;
 });

 let nodeInfo = $derived.by(() => {
  const map = new Map<string, { layer: number; type: string }>();
  const nodes = (graphJson as { nodes: Record<string, Record<string, unknown>> }).nodes;
  if (!nodes) return map;
  for (const [id, data] of Object.entries(nodes)) {
   map.set(id, {
    layer: (data.layer as number) ?? 0,
    type: (data.type as string) ?? 'mini_dungeon'
   });
  }
  return map;
 });

 let replayParticipants = $derived(buildReplayParticipants(allParticipants, graphJson));
 let maxIgt = $derived(Math.max(...replayParticipants.map((rp) => rp.totalIgt), 0));
 let skullEvents = $derived(collectSkullEvents(replayParticipants));
 let ghostIds = $derived(new Set(ghosts.map((g) => g.id)));

 // Label placement
 let labelAbove = $derived.by(() => {
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

 // Animation state
 let replayState: ReplayState = $state('idle');
 let speed = $state(1);
 let replayElapsedMs = $state(0);
 let currentIgt = $state(0);
 let animationFrameId: number | null = null;
 let lastFrameTime: number | null = null;

 // Leader tracking
 let leaderId: string | null = $state(null);
 let previousLeader: string | null = $state(null);

 function handleLeaderChange(newLeaderId: string | null) {
  previousLeader = leaderId;
  leaderId = newLeaderId;
 }

 function tick(timestamp: number) {
  if (lastFrameTime === null) {
   lastFrameTime = timestamp;
   animationFrameId = requestAnimationFrame(tick);
   return;
  }

  const delta = (timestamp - lastFrameTime) * speed;
  lastFrameTime = timestamp;
  replayElapsedMs += delta;

  currentIgt = replayMsToIgt(replayElapsedMs, maxIgt);

  if (replayElapsedMs >= REPLAY_DEFAULTS.DURATION_MS) {
   replayState = 'finished';
   currentIgt = maxIgt;
   animationFrameId = null;
   lastFrameTime = null;
   return;
  }

  animationFrameId = requestAnimationFrame(tick);
 }

 function play() {
  if (replayState === 'finished') {
   replayElapsedMs = 0;
   currentIgt = 0;
   previousLeader = null;
  }
  replayState = 'playing';
  lastFrameTime = null;
  animationFrameId = requestAnimationFrame(tick);
 }

 function pause() {
  replayState = 'paused';
  if (animationFrameId !== null) {
   cancelAnimationFrame(animationFrameId);
   animationFrameId = null;
  }
  lastFrameTime = null;
 }

 function seek(progress: number) {
  replayElapsedMs = progress * REPLAY_DEFAULTS.DURATION_MS;
  currentIgt = replayMsToIgt(replayElapsedMs, maxIgt);
  if (replayState === 'idle' || (replayState === 'finished' && progress < 1)) {
   replayState = 'paused';
  }
 }

 function setSpeed(s: number) {
  speed = s;
 }

 $effect(() => {
  return () => {
   if (animationFrameId !== null) {
    cancelAnimationFrame(animationFrameId);
   }
  };
 });

 let progress = $derived(
  REPLAY_DEFAULTS.DURATION_MS > 0 ? replayElapsedMs / REPLAY_DEFAULTS.DURATION_MS : 0
 );
</script>

{#if replayParticipants.length >= 1 && maxIgt > 0}
 <div class="training-replay">
  <div class="replay-dag-container">
   <ZoomableSvg width={layout.width} height={layout.height}>
    <defs>
     <filter id="replay-player-glow" x="-50%" y="-50%" width="200%" height="200%">
      <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
      <feMerge>
       <feMergeNode in="blur" />
       <feMergeNode in="SourceGraphic" />
      </feMerge>
     </filter>
    </defs>

    <DagBaseLayer {layout} {labelAbove} />

    {#if replayState !== 'idle'}
     <ReplayDag
      {currentIgt}
      {replayElapsedMs}
      {maxIgt}
      {replayParticipants}
      {skullEvents}
      {nodePositions}
      {nodeInfo}
      {leaderId}
      {previousLeader}
      {ghostIds}
      onleaderchange={handleLeaderChange}
     />
    {/if}
   </ZoomableSvg>
  </div>

  <ReplayControls
   {replayState}
   {progress}
   {speed}
   ghostCount={ghosts.length}
   onplay={play}
   onpause={pause}
   onseek={seek}
   onspeed={setSpeed}
  />
 </div>
{/if}

<style>
 .training-replay {
  display: flex;
  flex-direction: column;
 }

 .replay-dag-container {
  position: relative;
  background: var(--color-surface);
  border-radius: var(--radius-lg) var(--radius-lg) 0 0;
  overflow: hidden;
 }
</style>
```

### Step 2: Add TrainingReplay export

In `web/src/lib/replay/` check if there's an index file. If not, the import will be direct. The training page will import `TrainingReplay` directly from its path.

### Step 3: Integrate into the training detail page

In `web/src/routes/training/[id]/+page.svelte`:

**Add imports** (at the top of the script block, after existing imports):

```typescript
import { fetchTrainingGhosts, type Ghost } from "$lib/api";
import TrainingReplay from "$lib/replay/TrainingReplay.svelte";
```

**Add ghost state** (after the existing state declarations, around line 24):

```typescript
let ghosts = $state<Ghost[]>([]);
let dagView = $state<"map" | "replay">("map");
```

**Add ghost fetching** (in the `loadSession` function, after `session = await fetchTrainingSession(sessionId)`):

```typescript
async function loadSession() {
  try {
    session = await fetchTrainingSession(sessionId);
    // Fetch ghosts in background for finished sessions
    if (session.status === "finished") {
      fetchTrainingGhosts(sessionId).then((g) => {
        ghosts = g;
      });
    }
  } catch (e) {
    error = e instanceof Error ? e.message : "Failed to load session.";
  } finally {
    loading = false;
  }
}
```

**Add ghost WsParticipant builder** (after the `dagParticipants` derived, around line 62):

```typescript
let ghostParticipants = $derived.by(() => {
  return ghosts.map((g, i) => ({
    id: `ghost-${i}`,
    twitch_username: `Ghost ${i + 1}`,
    twitch_display_name: null,
    status: "finished" as const,
    current_zone: g.zone_history[g.zone_history.length - 1]?.node_id ?? null,
    current_layer: 0,
    igt_ms: g.igt_ms,
    death_count: g.death_count,
    color_index: -1, // Will be overridden — gray in buildReplayParticipants
    mod_connected: false,
    zone_history: g.zone_history,
  }));
});
```

Wait — the color issue. `buildReplayParticipants` uses `PLAYER_COLORS[p.color_index % PLAYER_COLORS.length]` which won't produce gray for `-1`. We need to handle this differently.

Better approach: Override the color AFTER `buildReplayParticipants` runs, in `TrainingReplay.svelte`. Actually, the cleanest: in `TrainingReplay.svelte`, after building `replayParticipants`, override the ghost colors:

In `TrainingReplay.svelte`, replace the `replayParticipants` derived:

```typescript
let replayParticipants = $derived.by(() => {
  const rps = buildReplayParticipants(allParticipants, graphJson);
  // Override ghost colors to gray
  for (const rp of rps) {
    if (ghostIds.has(rp.id)) {
      rp.color = "#888888";
    }
  }
  return rps;
});
```

But `ghostIds` is also derived from `ghosts` — this creates a dependency cycle issue if we reference it before definition. Let me restructure: compute `ghostIds` before `replayParticipants`.

In `TrainingReplay.svelte`, reorder the derived values:

```typescript
let ghostIds = $derived(new Set(ghosts.map((g) => g.id)));

let replayParticipants = $derived.by(() => {
  const rps = buildReplayParticipants(allParticipants, graphJson);
  for (const rp of rps) {
    if (ghostIds.has(rp.id)) {
      rp.color = "#888888";
    }
  }
  return rps;
});
```

This is clean — `ghostIds` only depends on `ghosts` prop, then `replayParticipants` uses it.

### Step 4: Update the DAG section in the template

Replace the DAG section (lines 215-239) in the training detail page:

```svelte
<!-- DAG section -->
{#if graphJson}
    <section class="dag-section">
        {#if status === 'finished' && dagParticipants.length > 0}
            <div class="dag-view-toggle">
                <button class="toggle-btn" class:active={dagView === 'map'} onclick={() => (dagView = 'map')}>Map</button>
                <button class="toggle-btn" class:active={dagView === 'replay'} onclick={() => (dagView = 'replay')}>Replay</button>
            </div>
            {#if dagView === 'map'}
                <MetroDagFull {graphJson} participants={dagParticipants} />
            {:else}
                <TrainingReplay
                    {graphJson}
                    currentPlayer={dagParticipants[0]}
                    ghosts={ghostParticipants}
                />
            {/if}
        {:else if status === 'abandoned' && dagParticipants.length > 0}
            <MetroDagFull {graphJson} participants={dagParticipants} />
        {:else if status === 'active' && dagParticipants.length > 0}
            <button class="btn btn-secondary btn-sm" onclick={() => (showFullDag = !showFullDag)}>
                {showFullDag ? 'Hide Spoiler' : 'Show Spoiler'}
            </button>
            <div class="dag-wrapper">
                {#if showFullDag}
                    <MetroDagFull {graphJson} participants={dagParticipants} />
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

### Step 5: Add toggle button styles

In the `<style>` block of the training page, add the toggle styles (copy from race page):

```css
.dag-view-toggle {
  display: flex;
  gap: 0.25rem;
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 0.25rem;
  width: fit-content;
  margin-bottom: 0.75rem;
}

.toggle-btn {
  all: unset;
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  color: var(--color-text-disabled);
  padding: 0.35rem 0.9rem;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all var(--transition);
}

.toggle-btn:hover {
  color: var(--color-text-secondary);
}

.toggle-btn.active {
  background: var(--color-border);
  color: var(--color-text);
  font-weight: 600;
}
```

### Step 6: Run type checking and lint

Run: `cd web && npm run check`
Run: `cd web && npm run lint`

### Step 7: Commit

```bash
git add web/src/lib/replay/TrainingReplay.svelte web/src/routes/training/\[id\]/+page.svelte web/src/lib/api.ts
git commit -m "feat(training): add ghost replay to training detail page"
```

---

## Task 6: Final Verification

### Step 1: Run full server test suite

Run: `cd server && uv run pytest -x -q`

### Step 2: Run full frontend checks

Run: `cd web && npm run check && npm run lint`

### Step 3: Run server linting

Run: `cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/`

### Step 4: Manual verification checklist

- [ ] Training detail page for a FINISHED session shows "Map / Replay" toggle
- [ ] Training detail page for ACTIVE session does NOT show replay toggle
- [ ] Training detail page for ABANDONED session does NOT show replay toggle
- [ ] Clicking "Replay" shows the animated replay with player dot in color
- [ ] Ghost dots appear in gray with reduced opacity
- [ ] Ghost skulls appear with reduced opacity
- [ ] Ghost count shows correctly in the controls bar
- [ ] Play/pause/scrub/speed controls work as expected
- [ ] If no ghosts exist, solo replay still works (single dot)
