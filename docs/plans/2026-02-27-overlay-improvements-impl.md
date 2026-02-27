# Overlay Improvements Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Improve OBS overlay experience with leaderboard line limits, DAG pre-race calibration, auto-zoom follow mode, and live player dots/skulls.

**Architecture:** URL query parameters drive overlay behavior. The leaderboard slices its data to `lines`. The DAG overlay gains a `follow` mode that computes viewport transform from player positions, a `hideLabels` prop for pre-race calibration, and live player dots/skulls adapted from the ReplayDag system. All parameters are configurable via the existing ObsOverlayModal.

**Tech Stack:** SvelteKit 5 (runes), TypeScript, SVG

---

## Task 1: Leaderboard `lines` parameter

**Files:**

- Modify: `web/src/routes/overlay/race/[id]/leaderboard/+page.svelte`
- Modify: `web/src/lib/components/LeaderboardOverlay.svelte`

### Step 1: Add `lines` prop to LeaderboardOverlay

In `web/src/lib/components/LeaderboardOverlay.svelte`, add an optional `lines` prop and slice the participants array.

```svelte
<!-- In the Props interface (line 5-9) -->
interface Props {
    participants: WsParticipant[];
    totalLayers?: number | null;
    mode?: 'running' | 'finished';
    lines?: number | null;
}

let { participants, totalLayers = null, mode = 'running', lines = null }: Props = $props();

let visibleParticipants = $derived(
    lines != null && lines > 0 ? participants.slice(0, lines) : participants
);
```

Then replace `{#each participants as participant, index (participant.id)}` with `{#each visibleParticipants as participant, index (participant.id)}`.

### Step 2: Read `lines` from URL in the overlay page

In `web/src/routes/overlay/race/[id]/leaderboard/+page.svelte`, read the query param and pass it down:

```svelte
<script lang="ts">
    import { page } from '$app/state';
    // ... existing imports ...

    let lines = $derived((() => {
        const raw = page.url.searchParams.get('lines');
        if (raw === null || raw === '') return 10; // default
        const n = parseInt(raw, 10);
        return isNaN(n) || n <= 0 ? null : n;
    })());
</script>

<div class="leaderboard-overlay">
    <LeaderboardOverlay participants={raceStore.leaderboard} {totalLayers} {mode} {lines} />
</div>
```

### Step 3: Verify locally

Run: `cd web && npm run dev`

Open `/overlay/race/{id}/leaderboard` — should show max 10 players.
Open `/overlay/race/{id}/leaderboard?lines=3` — should show only top 3.
Open `/overlay/race/{id}/leaderboard?lines=` — should show all players (no limit).

### Step 4: Run type check

Run: `cd web && npm run check`
Expected: no new errors.

### Step 5: Commit

```
feat(web): add lines parameter to leaderboard overlay

Limits the number of displayed rows in the leaderboard overlay via
?lines=N query parameter (default 10). Streamers can control overlay
height by adjusting this value.
```

---

## Task 2: ObsOverlayModal — leaderboard lines config

**Files:**

- Modify: `web/src/lib/components/ObsOverlayModal.svelte`

### Step 1: Add lines input and update URL generation

Add a `$state` for `lbLines` (default 10), a numeric input field, and update the `lbUrl` derivation:

```svelte
<script lang="ts">
    // ... existing props/state ...
    let lbLines = $state<number | null>(10);
    let dagFollow = $state(false);

    let dagUrl = $derived(
        typeof window !== 'undefined'
            ? `${window.location.origin}/overlay/race/${raceId}/dag${dagFollow ? '?follow=true' : ''}`
            : ''
    );

    let lbUrl = $derived(
        typeof window !== 'undefined'
            ? `${window.location.origin}/overlay/race/${raceId}/leaderboard${lbLines != null ? `?lines=${lbLines}` : ''}`
            : ''
    );
</script>
```

### Step 2: Add UI controls in the modal template

In the Leaderboard `overlay-section`, after the size hint, add a config row:

```svelte
<div class="overlay-section">
    <h3>Leaderboard</h3>
    <p class="size-hint">Recommended size: 400 &times; 800</p>
    <div class="config-row">
        <label for="lb-lines">Max lines</label>
        <input
            id="lb-lines"
            type="number"
            min="1"
            max="50"
            bind:value={lbLines}
            placeholder="All"
            class="config-input"
        />
    </div>
    <div class="url-row">
        <!-- existing url input + copy button -->
    </div>
</div>
```

In the DAG `overlay-section`, after the size hint, add a checkbox:

```svelte
<div class="config-row">
    <label for="dag-follow">
        <input id="dag-follow" type="checkbox" bind:checked={dagFollow} />
        Auto-follow
    </label>
</div>
```

### Step 3: Add CSS for config rows

```css
.config-row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  margin-bottom: 0.5rem;
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
}

.config-input {
  width: 5rem;
  padding: 0.25rem 0.5rem;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-family: "JetBrains Mono", "Fira Code", monospace;
  font-size: var(--font-size-sm);
}

.config-row label {
  display: flex;
  align-items: center;
  gap: 0.4rem;
  cursor: pointer;
}
```

### Step 4: Run type check

Run: `cd web && npm run check`
Expected: no new errors.

### Step 5: Commit

```
feat(web): add overlay config controls to ObsOverlayModal

Adds numeric input for leaderboard max lines (default 10) and
auto-follow checkbox for DAG overlay. Both update the generated
URL in real time.
```

---

## Task 3: DAG pre-race — `hideLabels` prop on MetroDagFull

**Files:**

- Modify: `web/src/lib/dag/MetroDagFull.svelte`
- Modify: `web/src/routes/overlay/race/[id]/dag/+page.svelte`

### Step 1: Add `hideLabels` prop to MetroDagFull

In `web/src/lib/dag/MetroDagFull.svelte`, add the prop to the interface (line 32-39):

```typescript
interface Props {
  graphJson: Record<string, unknown>;
  participants: WsParticipant[];
  raceStatus?: string;
  transparent?: boolean;
  highlightIds?: Set<string>;
  focusNodeId?: string | null;
  hideLabels?: boolean;
}

let {
  graphJson,
  participants,
  raceStatus,
  transparent = false,
  highlightIds,
  focusNodeId = null,
  hideLabels = false,
}: Props = $props();
```

### Step 2: Conditionally hide labels in the template

In the label `<text>` element (around line 457-468), wrap with a condition:

```svelte
<!-- Label -->
{#if !hideLabels}
    <text
        x={labelX(node)}
        y={labelY(node)}
        text-anchor={labelAbove.has(node.id) ? 'start' : 'end'}
        font-size={LABEL_FONT_SIZE}
        fill={LABEL_COLOR}
        class="dag-label"
        class:transparent-label={transparent}
        transform="rotate(-30, {labelX(node)}, {labelY(node)})"
    >
        {truncateLabel(node.displayName)}
    </text>
{/if}
```

Also hide the death icons when labels are hidden (same block, around line 445-454):

```svelte
{#if !hideLabels && nodesWithDeaths.has(node.id)}
```

### Step 3: Update DAG overlay page to use real DAG in setup

In `web/src/routes/overlay/race/[id]/dag/+page.svelte`, change the rendering logic:

```svelte
<div class="dag-overlay">
    {#if liveSeed?.graph_json && (raceStatus === 'running' || raceStatus === 'finished')}
        <MetroDagFull graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} {raceStatus} transparent />
    {:else if liveSeed?.graph_json && raceStatus === 'setup'}
        <MetroDagFull graphJson={liveSeed.graph_json} participants={[]} raceStatus="setup" transparent hideLabels />
    {:else if totalNodes && totalPaths && totalLayers}
        <MetroDagBlurred {totalLayers} {totalNodes} {totalPaths} transparent />
    {/if}
</div>
```

The `MetroDagBlurred` fallback remains for when `graph_json` is not yet available.

### Step 4: Run type check

Run: `cd web && npm run check`
Expected: no new errors.

### Step 5: Commit

```
feat(web): show real DAG structure with hidden labels during setup

Replaces blurred fake DAG with the real DAG layout (nodes and edges
visible, labels hidden) when graph_json is available during setup.
Streamers can calibrate their OBS overlay on the actual DAG shape.
Falls back to MetroDagBlurred when graph_json is unavailable.
```

---

## Task 4: Live player dots with orbit animation

**Files:**

- Create: `web/src/lib/dag/LivePlayerDots.svelte`
- Modify: `web/src/lib/dag/MetroDagFull.svelte`
- Modify: `web/src/lib/dag/constants.ts`

This adapts the ReplayDag dot/skull system for live data. Key difference: ReplayDag uses pre-computed `zone_history` with IGT-based timeline; the live overlay uses `current_zone` from WebSocket updates and wall-clock time for orbit animation.

### Step 1: Add live overlay constants to constants.ts

In `web/src/lib/dag/constants.ts`, add at the end:

```typescript
// =============================================================================
// Live overlay player dots
// =============================================================================

/** Orbit radius for live player dots (SVG px) */
export const LIVE_ORBIT_RADIUS = 9;

/** Orbit period for live dots (ms wall-clock) */
export const LIVE_ORBIT_PERIOD_MS = 2000;

/** Duration of skull pop-and-fade animation (ms) */
export const LIVE_SKULL_ANIM_MS = 1500;

/** Skull peak scale (overshoot) */
export const LIVE_SKULL_PEAK_SCALE = 2.0;

/** X offset for finished player dots right of final node (px) */
export const LIVE_FINISHED_X_OFFSET = 20;

/** X offset for setup player dots left of start node (px) */
export const LIVE_START_X_OFFSET = -20;
```

### Step 2: Create LivePlayerDots.svelte

Create `web/src/lib/dag/LivePlayerDots.svelte`. This component renders orbiting dots and skull animations for live race participants.

```svelte
<script lang="ts">
    import type { WsParticipant } from '$lib/websocket';
    import type { PositionedNode } from './types';
    import {
        PLAYER_COLORS,
        RACER_DOT_RADIUS,
        LIVE_ORBIT_RADIUS,
        LIVE_ORBIT_PERIOD_MS,
        LIVE_SKULL_ANIM_MS,
        LIVE_SKULL_PEAK_SCALE,
        LIVE_FINISHED_X_OFFSET,
        LIVE_START_X_OFFSET
    } from './constants';

    interface Props {
        participants: WsParticipant[];
        nodeMap: Map<string, PositionedNode>;
        raceStatus?: string;
        /** Show dots in pre-race position (aligned left of start) */
        preRace?: boolean;
    }

    let { participants, nodeMap, raceStatus, preRace = false }: Props = $props();

    // Wall-clock elapsed time for orbit animation
    let elapsed = $state(0);
    let frameId: number;

    $effect(() => {
        const start = performance.now();
        function tick() {
            elapsed = performance.now() - start;
            frameId = requestAnimationFrame(tick);
        }
        frameId = requestAnimationFrame(tick);
        return () => cancelAnimationFrame(frameId);
    });

    // Find start node (type === 'start') for pre-race positioning
    let startNode = $derived.by(() => {
        for (const node of nodeMap.values()) {
            if (node.type === 'start') return node;
        }
        return null;
    });

    // Find final boss node for finished positioning
    let finalBossNode = $derived.by(() => {
        for (const node of nodeMap.values()) {
            if (node.type === 'final_boss') return node;
        }
        return null;
    });

    // Track previous death counts to detect new deaths
    let prevDeaths = $state(new Map<string, number>());
    interface SkullAnim {
        id: string;
        participantId: string;
        nodeId: string;
        startTime: number;
    }
    let skulls = $state<SkullAnim[]>([]);

    $effect(() => {
        const now = performance.now();
        const newSkulls: SkullAnim[] = [];
        for (const p of participants) {
            const prev = prevDeaths.get(p.id) ?? 0;
            if (p.death_count > prev && p.current_zone) {
                for (let i = 0; i < p.death_count - prev; i++) {
                    newSkulls.push({
                        id: `${p.id}-${now}-${i}`,
                        participantId: p.id,
                        nodeId: p.current_zone,
                        startTime: now
                    });
                }
            }
            prevDeaths.set(p.id, p.death_count);
        }
        if (newSkulls.length > 0) {
            skulls = [...skulls.filter(s => performance.now() - s.startTime < LIVE_SKULL_ANIM_MS), ...newSkulls];
        }
    });

    // Clean up expired skulls periodically
    $effect(() => {
        // Re-run when elapsed changes (every frame)
        void elapsed;
        skulls = skulls.filter(s => performance.now() - s.startTime < LIVE_SKULL_ANIM_MS);
    });

    interface DotPosition {
        participantId: string;
        x: number;
        y: number;
        color: string;
        displayName: string;
        opacity: number;
    }

    let dots: DotPosition[] = $derived.by(() => {
        const result: DotPosition[] = [];
        const playingAtNode = new Map<string, number>();

        for (let i = 0; i < participants.length; i++) {
            const p = participants[i];
            const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
            const displayName = p.twitch_display_name || p.twitch_username;

            if (preRace && startNode) {
                // Pre-race: align left of start node
                const spacing = RACER_DOT_RADIUS * 2;
                const totalSpread = (participants.length - 1) * spacing;
                const yOffset = -totalSpread / 2 + i * spacing;
                result.push({
                    participantId: p.id,
                    x: startNode.x + LIVE_START_X_OFFSET,
                    y: startNode.y + yOffset,
                    color,
                    displayName,
                    opacity: 1
                });
                continue;
            }

            if (p.status === 'finished' && finalBossNode) {
                // Finished: align right of final boss
                const finishedPlayers = participants.filter(pp => pp.status === 'finished');
                const idx = finishedPlayers.indexOf(p);
                const spacing = RACER_DOT_RADIUS * 2;
                const totalSpread = (finishedPlayers.length - 1) * spacing;
                const yOffset = -totalSpread / 2 + idx * spacing;
                result.push({
                    participantId: p.id,
                    x: finalBossNode.x + LIVE_FINISHED_X_OFFSET,
                    y: finalBossNode.y + yOffset,
                    color,
                    displayName,
                    opacity: 1
                });
                continue;
            }

            if (p.status === 'abandoned' && p.current_zone) {
                const node = nodeMap.get(p.current_zone);
                if (node) {
                    result.push({
                        participantId: p.id,
                        x: node.x,
                        y: node.y,
                        color,
                        displayName,
                        opacity: 0.35
                    });
                }
                continue;
            }

            if ((p.status === 'playing' || p.status === 'ready') && p.current_zone) {
                const node = nodeMap.get(p.current_zone);
                if (node) {
                    // Count how many players are at this node for phase offset
                    const countAtNode = playingAtNode.get(p.current_zone) ?? 0;
                    playingAtNode.set(p.current_zone, countAtNode + 1);

                    const phaseOffset = (countAtNode / Math.max(participants.length, 1)) * Math.PI * 2;
                    const angle = phaseOffset + (elapsed / LIVE_ORBIT_PERIOD_MS) * Math.PI * 2;
                    result.push({
                        participantId: p.id,
                        x: node.x + Math.cos(angle) * LIVE_ORBIT_RADIUS,
                        y: node.y + Math.sin(angle) * LIVE_ORBIT_RADIUS,
                        color,
                        displayName,
                        opacity: 1
                    });
                }
                continue;
            }
        }
        return result;
    });

    function skullScale(progress: number): number {
        if (progress < 0.3) return (progress / 0.3) * LIVE_SKULL_PEAK_SCALE;
        if (progress < 0.5) {
            const overshoot = LIVE_SKULL_PEAK_SCALE - 1.0;
            return LIVE_SKULL_PEAK_SCALE - ((progress - 0.3) / 0.2) * overshoot;
        }
        return 1.0;
    }

    function skullOpacity(progress: number): number {
        if (progress < 0.5) return 1;
        return 1 - (progress - 0.5) / 0.5;
    }
</script>

<!-- Player dots -->
{#each dots as dot (dot.participantId)}
    <circle
        cx={dot.x}
        cy={dot.y}
        r={RACER_DOT_RADIUS}
        fill={dot.color}
        opacity={dot.opacity}
        filter={dot.opacity < 1 ? undefined : 'url(#live-player-glow)'}
        class="live-dot"
    >
        <title>{dot.displayName}</title>
    </circle>
{/each}

<!-- Skull animations -->
{#each skulls as skull (skull.id)}
    {@const pos = nodeMap.get(skull.nodeId)}
    {@const progress = (performance.now() - skull.startTime) / LIVE_SKULL_ANIM_MS}
    {#if pos && progress < 1}
        <text
            x={pos.x}
            y={pos.y}
            text-anchor="middle"
            dominant-baseline="central"
            font-size={18 * skullScale(progress)}
            opacity={skullOpacity(progress)}
            class="skull-anim"
        >&#x1F480;</text>
    {/if}
{/each}

<style>
    .live-dot {
        pointer-events: none;
    }
    .skull-anim {
        pointer-events: none;
    }
</style>
```

### Step 3: Integrate LivePlayerDots into MetroDagFull

In `web/src/lib/dag/MetroDagFull.svelte`:

1. Add import: `import LivePlayerDots from './LivePlayerDots.svelte';`

2. Add props `hideLabels` and `showLiveDots`:

```typescript
interface Props {
  // ... existing ...
  hideLabels?: boolean;
  showLiveDots?: boolean;
}
```

1. Inside the `<ZoomableSvg>`, after the existing "Final position dots" block and before the closing `</ZoomableSvg>`, add a `<defs>` filter and the component:

```svelte
<!-- In defs (alongside existing filter) -->
<filter id="live-player-glow" x="-50%" y="-50%" width="200%" height="200%">
    <feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
    <feMerge>
        <feMergeNode in="blur" />
        <feMergeNode in="SourceGraphic" />
    </feMerge>
</filter>

<!-- After final position dots, conditionally render live dots -->
{#if showLiveDots}
    <LivePlayerDots {participants} {nodeMap} {raceStatus} preRace={raceStatus === 'setup'} />
{/if}
```

1. When `showLiveDots` is true, the existing player path polylines and final position dots should be conditionally hidden or shown based on the overlay context. This will be handled in Task 6 (follow mode integration).

### Step 4: Run type check

Run: `cd web && npm run check`
Expected: no new errors.

### Step 5: Commit

```
feat(web): add LivePlayerDots component for live overlay

Renders orbiting player dots around current nodes, skull pop-and-fade
on deaths, start-aligned dots pre-race, and finish-aligned dots for
finished players. Adapted from ReplayDag animation system for live
WebSocket data.
```

---

## Task 5: Auto-follow viewport — FollowViewport component

**Files:**

- Create: `web/src/lib/dag/FollowViewport.svelte`

This is the core auto-zoom component. It replaces `ZoomableSvg` when `follow=true`, computing viewport transform from player positions.

### Step 1: Create FollowViewport.svelte

Create `web/src/lib/dag/FollowViewport.svelte`:

```svelte
<script lang="ts">
    import type { WsParticipant } from '$lib/websocket';
    import type { PositionedNode } from './types';

    interface Props {
        width: number;
        height: number;
        participants: WsParticipant[];
        nodeMap: Map<string, PositionedNode>;
        raceStatus?: string;
        transparent?: boolean;
        children: import('svelte').Snippet;
    }

    let {
        width,
        height,
        participants,
        nodeMap,
        raceStatus,
        transparent = false,
        children
    }: Props = $props();

    // Find the X range of all layers from the layout
    let layerXPositions = $derived.by(() => {
        const xs = new Map<number, number>();
        for (const node of nodeMap.values()) {
            if (!xs.has(node.layer) || node.x < xs.get(node.layer)!) {
                xs.set(node.layer, node.x);
            }
        }
        return xs;
    });

    let totalLayers = $derived(layerXPositions.size);
    let minX = $derived(Math.min(...nodeMap.values().map(n => n.x)) || 0);
    let maxX = $derived(Math.max(...nodeMap.values().map(n => n.x)) || width);

    // Max visible layers: ~50% of total
    let maxVisibleLayers = $derived(Math.max(3, Math.ceil(totalLayers / 2)));

    // Compute target viewport based on race status
    let viewport = $derived.by(() => {
        if (raceStatus === 'finished') {
            // Show full DAG
            return { centerX: width / 2, centerY: height / 2, visibleWidth: width, visibleHeight: height };
        }

        const activePlayers = participants.filter(p => p.status === 'playing');

        if (raceStatus === 'setup' || activePlayers.length === 0) {
            // Zoom on start area — find start node
            let startX = minX;
            for (const node of nodeMap.values()) {
                if (node.type === 'start') { startX = node.x; break; }
            }
            // Show maxVisibleLayers worth of width from the start
            const layerWidth = totalLayers > 1 ? (maxX - minX) / (totalLayers - 1) : 100;
            const visibleWidth = layerWidth * maxVisibleLayers;
            return {
                centerX: startX + visibleWidth / 2 - layerWidth / 2,
                centerY: height / 2,
                visibleWidth,
                visibleHeight: height
            };
        }

        // Running: compute from active player positions
        const playerLayers = activePlayers.map(p => p.current_layer);
        const minLayer = Math.min(...playerLayers);
        const maxLayer = Math.max(...playerLayers);
        const layerSpan = maxLayer - minLayer + 1;

        // Convert layers to X positions
        const sortedXs = [...layerXPositions.entries()].sort((a, b) => a[0] - b[0]);
        const layerToX = (layer: number): number => {
            const entry = sortedXs.find(([l]) => l === layer);
            if (entry) return entry[1];
            // Interpolate
            const layerWidth = totalLayers > 1 ? (maxX - minX) / (totalLayers - 1) : 100;
            return minX + layer * layerWidth;
        };

        // Barycenter of active players
        const avgLayer = playerLayers.reduce((s, l) => s + l, 0) / playerLayers.length;
        const centerX = layerToX(avgLayer);

        // Visible width: at least maxVisibleLayers, or enough to show all players + margin
        const visibleLayers = Math.max(layerSpan + 2, maxVisibleLayers);
        const layerWidth = totalLayers > 1 ? (maxX - minX) / (totalLayers - 1) : 100;
        let visibleWidth = layerWidth * visibleLayers;

        // Clamp visible width to full DAG width (don't zoom out more than 1:1)
        visibleWidth = Math.min(visibleWidth, width);

        // Clamp center so we don't go past first/last layer
        const halfVisible = visibleWidth / 2;
        const clampedCenterX = Math.max(minX + halfVisible, Math.min(maxX - halfVisible, centerX));

        return {
            centerX: clampedCenterX,
            centerY: height / 2,
            visibleWidth,
            visibleHeight: height
        };
    });

    // Convert viewport to SVG viewBox with smooth animation
    let targetViewBox = $derived(
        `${viewport.centerX - viewport.visibleWidth / 2} ${viewport.centerY - viewport.visibleHeight / 2} ${viewport.visibleWidth} ${viewport.visibleHeight}`
    );

    // Off-screen indicators: players outside the current viewport
    interface OffscreenIndicator {
        participantId: string;
        displayName: string;
        color: string;
        side: 'left' | 'right';
        y: number;
    }

    let offscreenIndicators = $derived.by(() => {
        if (raceStatus !== 'running') return [];

        const vLeft = viewport.centerX - viewport.visibleWidth / 2;
        const vRight = viewport.centerX + viewport.visibleWidth / 2;
        const indicators: OffscreenIndicator[] = [];

        for (const p of participants) {
            if (p.status !== 'playing' || !p.current_zone) continue;
            const node = nodeMap.get(p.current_zone);
            if (!node) continue;

            if (node.x < vLeft) {
                indicators.push({
                    participantId: p.id,
                    displayName: p.twitch_display_name || p.twitch_username,
                    color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
                    side: 'left',
                    y: node.y
                });
            } else if (node.x > vRight) {
                indicators.push({
                    participantId: p.id,
                    displayName: p.twitch_display_name || p.twitch_username,
                    color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
                    side: 'right',
                    y: node.y
                });
            }
        }
        return indicators;
    });

    import { PLAYER_COLORS } from './constants';
</script>

<div class="follow-container" class:transparent>
    {#if width > 0 && height > 0}
        <svg
            viewBox={targetViewBox}
            preserveAspectRatio="xMidYMid meet"
            class="follow-svg"
            role="img"
        >
            {@render children()}
        </svg>

        <!-- Off-screen indicators (rendered as HTML overlays) -->
        {#each offscreenIndicators as ind (ind.participantId)}
            <div
                class="offscreen-indicator"
                class:left={ind.side === 'left'}
                class:right={ind.side === 'right'}
                style="--player-color: {ind.color};"
            >
                <span class="offscreen-chevron">{ind.side === 'left' ? '◀' : '▶'}</span>
                <span class="offscreen-name">{ind.displayName}</span>
            </div>
        {/each}
    {/if}
</div>

<style>
    .follow-container {
        position: relative;
        width: 100%;
        background: var(--color-surface, #1a1a2e);
        border-radius: var(--radius-lg, 8px);
        min-height: 200px;
        display: flex;
        align-items: center;
        justify-content: center;
        overflow: hidden;
    }

    .follow-container.transparent {
        background: transparent;
        border-radius: 0;
    }

    .follow-svg {
        display: block;
        width: 100%;
        min-width: 600px;
        user-select: none;
        /* Smooth viewport transitions */
        transition: viewBox 1s ease-out;
    }

    .offscreen-indicator {
        position: absolute;
        top: 50%;
        display: flex;
        align-items: center;
        gap: 0.25rem;
        padding: 0.2rem 0.5rem;
        font-size: 11px;
        font-family: 'JetBrains Mono', 'Fira Code', monospace;
        color: var(--player-color);
        text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
        pointer-events: none;
    }

    .offscreen-indicator.left {
        left: 4px;
    }

    .offscreen-indicator.right {
        right: 4px;
    }

    .offscreen-chevron {
        font-size: 14px;
    }

    .offscreen-name {
        font-weight: 600;
        white-space: nowrap;
    }
</style>
```

**Note:** SVG `viewBox` cannot be animated via CSS `transition`. The smooth viewport change will be implemented by interpolating the viewBox values in JS using `$effect` with `requestAnimationFrame`, lerping from previous to target viewBox over ~1s. This detail is left for implementation — the key logic is computing `viewport` from player positions, which is fully specified above.

### Step 2: Run type check

Run: `cd web && npm run check`
Expected: no new errors.

### Step 3: Commit

```
feat(web): add FollowViewport component for DAG auto-zoom

Computes viewport transform from active player positions. Centers on
barycenter, clamps to zoom min (~50% of layers visible), shows
off-screen indicators for players outside viewport. Transitions
smoothly between viewports on leaderboard updates.
```

---

## Task 6: Wire follow mode into DAG overlay page

**Files:**

- Modify: `web/src/routes/overlay/race/[id]/dag/+page.svelte`
- Modify: `web/src/lib/dag/MetroDagFull.svelte`

### Step 1: Read `follow` param and pass to MetroDagFull

In `web/src/routes/overlay/race/[id]/dag/+page.svelte`:

```svelte
<script lang="ts">
    import { page } from '$app/state';
    // ... existing imports ...

    let follow = $derived(page.url.searchParams.get('follow') === 'true');
</script>

<div class="dag-overlay">
    {#if liveSeed?.graph_json && (raceStatus === 'running' || raceStatus === 'finished')}
        <MetroDagFull
            graphJson={liveSeed.graph_json}
            participants={raceStore.leaderboard}
            {raceStatus}
            transparent
            {follow}
            showLiveDots
        />
    {:else if liveSeed?.graph_json && raceStatus === 'setup'}
        <MetroDagFull
            graphJson={liveSeed.graph_json}
            participants={raceStore.leaderboard}
            raceStatus="setup"
            transparent
            hideLabels
            {follow}
            showLiveDots
        />
    {:else if totalNodes && totalPaths && totalLayers}
        <MetroDagBlurred {totalLayers} {totalNodes} {totalPaths} transparent />
    {/if}
</div>
```

### Step 2: Add `follow` prop to MetroDagFull and swap container

In `web/src/lib/dag/MetroDagFull.svelte`:

1. Add to Props:

```typescript
interface Props {
  // ... existing ...
  hideLabels?: boolean;
  showLiveDots?: boolean;
  follow?: boolean;
}
```

1. Import FollowViewport: `import FollowViewport from './FollowViewport.svelte';`

1. Replace the single `<ZoomableSvg>` with a conditional:

```svelte
{#if follow}
    <FollowViewport
        width={layout.width}
        height={layout.height}
        {participants}
        {nodeMap}
        {raceStatus}
        {transparent}
    >
        <!-- Same SVG content as in ZoomableSvg children -->
        <!-- (defs, edges, player paths, nodes, live dots) -->
    </FollowViewport>
{:else}
    <ZoomableSvg width={layout.width} height={layout.height} {transparent} onnodeclick={onNodeClick} onpanstart={closePopup}>
        <!-- Same SVG content -->
    </ZoomableSvg>
{/if}
```

To avoid duplicating the SVG content, extract it into a Svelte snippet:

```svelte
{#snippet dagContent()}
    <defs>
        <filter id="results-player-glow" ...>...</filter>
        <filter id="live-player-glow" ...>...</filter>
    </defs>

    <!-- Base edges -->
    ...

    <!-- Player path polylines (conditional on follow mode) -->
    {#if !follow}
        {#each playerPaths as path (path.id)}
            <polyline ... />
        {/each}
    {:else}
        <!-- Trailing paths: render individual line segments with opacity gradient -->
        {#each trailingPaths as segment (segment.key)}
            <line
                x1={segment.x1} y1={segment.y1}
                x2={segment.x2} y2={segment.y2}
                stroke={segment.color}
                stroke-width="4"
                stroke-linecap="round"
                opacity={segment.opacity}
            />
        {/each}
    {/if}

    <!-- Nodes -->
    ...

    <!-- Live dots or static final dots -->
    {#if showLiveDots}
        <LivePlayerDots {participants} {nodeMap} {raceStatus} preRace={raceStatus === 'setup'} />
    {:else}
        {#each playerPaths as path (path.id)}
            <circle ... />
        {/each}
    {/if}
{/snippet}
```

### Step 3: Implement trailing path segments

Add a `trailingPaths` derived in `MetroDagFull.svelte` that computes the last N edge segments per player with decreasing opacity:

```typescript
interface TrailingSegment {
  key: string;
  x1: number;
  y1: number;
  x2: number;
  y2: number;
  color: string;
  opacity: number;
}

let trailingPaths: TrailingSegment[] = $derived.by(() => {
  if (!follow) return [];
  const TRAIL_LENGTH = 3; // number of segments to show
  const OPACITY_LEVELS = [0.8, 0.4, 0.15];
  const result: TrailingSegment[] = [];

  for (const p of participants) {
    if (!p.zone_history || p.zone_history.length < 2) continue;
    const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];

    // Take last TRAIL_LENGTH+1 zone entries to get TRAIL_LENGTH edges
    const recent = p.zone_history.slice(-TRAIL_LENGTH - 1);
    const edges: { from: string; to: string }[] = [];
    for (let i = 0; i < recent.length - 1; i++) {
      if (recent[i].node_id !== recent[i + 1].node_id) {
        edges.push({ from: recent[i].node_id, to: recent[i + 1].node_id });
      }
    }

    // Render most recent first
    for (let i = edges.length - 1; i >= 0; i--) {
      const age = edges.length - 1 - i;
      if (age >= TRAIL_LENGTH) break;
      const fromNode = nodeMap.get(edges[i].from);
      const toNode = nodeMap.get(edges[i].to);
      if (!fromNode || !toNode) continue;

      // Use edge routing for metro-style segments
      const edgeKey = `${edges[i].from}->${edges[i].to}`;
      const routedEdge =
        edgeMap.get(edgeKey) ?? edgeMap.get(`${edges[i].to}->${edges[i].from}`);
      if (routedEdge) {
        for (const seg of routedEdge.segments) {
          result.push({
            key: `${p.id}-${edgeKey}-${age}-${seg.x1}`,
            x1: seg.x1,
            y1: seg.y1,
            x2: seg.x2,
            y2: seg.y2,
            color,
            opacity: OPACITY_LEVELS[age] ?? 0,
          });
        }
      } else {
        // Straight line fallback
        result.push({
          key: `${p.id}-${edgeKey}-${age}`,
          x1: fromNode.x,
          y1: fromNode.y,
          x2: toNode.x,
          y2: toNode.y,
          color,
          opacity: OPACITY_LEVELS[age] ?? 0,
        });
      }
    }
  }
  return result;
});
```

### Step 4: Run type check

Run: `cd web && npm run check`
Expected: no new errors.

### Step 5: Test locally

Run: `cd web && npm run dev`

- Open `/overlay/race/{id}/dag` — should behave as before (manual zoom/pan, full paths, static final dots)
- Open `/overlay/race/{id}/dag?follow=true` — should show auto-zoom viewport with live dots and trailing paths
- During setup: viewport zoomed on start, dots aligned left
- During running: viewport follows barycenter, trails visible
- During finished: full zoom out

### Step 6: Commit

```
feat(web): wire follow mode into DAG overlay with trailing paths

Adds ?follow=true parameter to DAG overlay. When enabled, uses
FollowViewport for auto-zoom tracking, shows trailing path segments
with progressive opacity, and renders LivePlayerDots instead of
static polylines. Extracts SVG content into snippet to avoid
duplication between ZoomableSvg and FollowViewport containers.
```

---

## Task 7: Final type check + lint

**Files:** none (verification only)

### Step 1: Run full type check

Run: `cd web && npm run check`
Expected: PASS

### Step 2: Run linter

Run: `cd web && npm run lint`
Expected: PASS (or only pre-existing warnings)

### Step 3: Run formatter

Run: `cd web && npm run format`

### Step 4: Commit any formatting changes

```
style: format overlay improvement files
```
