# DAG Player Filtering — Implementation Plan

<!-- markdownlint-disable MD036 -->

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Click players in the Leaderboard sidebar to filter their paths on the MetroDagResults SVG. Ctrl+click for multi-select, Escape/Show All/re-click to reset.

**Architecture:** Local `Set<string>` state in `+page.svelte` flows down as props to Leaderboard (selection UI) and MetroDagResults (opacity filtering). Events bubble up from Leaderboard to page. No store, no persistence.

**Tech Stack:** SvelteKit 5 (runes: `$state`, `$derived`, `$props`), TypeScript, SVG opacity transitions.

**Design doc:** `docs/plans/2026-02-18-dag-player-filtering-design.md`

---

## Task 1: MetroDagResults — add `highlightIds` prop with opacity logic

Add the `highlightIds` optional prop and wire opacity on polylines and final-position dots.

**Files:**

- Modify: `web/src/lib/dag/MetroDagResults.svelte`

**Step 1: Add prop to interface and destructure**

In the `Props` interface (line 29-33), add `highlightIds`:

```svelte
interface Props {
 graphJson: Record<string, unknown>;
 participants: WsParticipant[];
 transparent?: boolean;
 highlightIds?: Set<string>;
}

let { graphJson, participants, transparent = false, highlightIds }: Props = $props();
```

**Step 2: Add a derived helper for checking highlight state**

After the `$props()` line, add:

```typescript
let hasHighlight = $derived(highlightIds != null && highlightIds.size > 0);
```

**Step 3: Apply opacity to polylines**

Change the `<polyline>` block (currently line 253-263). Replace the hardcoded `opacity="0.8"` with a dynamic value:

```svelte
{#each playerPaths as path (path.id)}
 <polyline
  points={path.points}
  fill="none"
  stroke={path.color}
  stroke-width="4"
  stroke-linecap="round"
  stroke-linejoin="round"
  opacity={hasHighlight && !highlightIds!.has(path.id) ? 0.1 : 0.8}
  class="player-path"
 >
  <title>{path.displayName}</title>
 </polyline>
{/each}
```

**Step 4: Apply opacity to final-position dots**

Change the final dots block (currently line 331-342). Replace static rendering with dynamic opacity:

```svelte
{#each playerPaths as path (path.id)}
 <circle
  cx={path.finalX}
  cy={path.finalY}
  r={RACER_DOT_RADIUS}
  fill={path.color}
  filter="url(#results-player-glow)"
  opacity={hasHighlight && !highlightIds!.has(path.id) ? 0.1 : 1}
  class="player-dot"
 >
  <title>{path.displayName}</title>
 </circle>
{/each}
```

**Step 5: Add CSS transition**

In the `<style>` block, add a transition rule for the new class:

```css
.player-path {
  transition: opacity 200ms ease;
}

.player-dot {
  pointer-events: auto;
  transition: opacity 200ms ease;
}
```

Remove the existing `.player-dot` rule (line 378-380) since it's replaced above.

**Step 6: Verify**

Run: `cd web && npm run check`
Expected: No type errors.

**Step 7: Commit**

```text
feat(dag): add highlightIds prop to MetroDagResults for player filtering
```

---

## Task 2: Leaderboard — add click handling, selection feedback, Show All, Escape

Make Leaderboard entries clickable and wire up selection UI.

**Files:**

- Modify: `web/src/lib/components/Leaderboard.svelte`

**Step 1: Add new props to interface**

Extend the `Props` interface (line 5-9) and destructure (line 12):

```svelte
interface Props {
 participants: WsParticipant[];
 totalLayers?: number | null;
 mode?: 'running' | 'finished';
 zoneNames?: Map<string, string> | null;
 selectedIds?: Set<string>;
 onToggle?: (id: string, ctrlKey: boolean) => void;
 onClearSelection?: () => void;
}

let {
 participants,
 totalLayers = null,
 mode = 'running',
 zoneNames = null,
 selectedIds,
 onToggle,
 onClearSelection
}: Props = $props();
```

**Step 2: Add derived helpers**

After the destructure:

```typescript
let hasSelection = $derived(selectedIds != null && selectedIds.size > 0);
```

**Step 3: Add Escape key listener**

Add a `<svelte:window>` handler. Place this before the `<div class="leaderboard">` in the template:

```svelte
<svelte:window
 onkeydown={(e) => {
  if (e.key === 'Escape' && hasSelection && onClearSelection) {
   onClearSelection();
  }
 }}
/>
```

**Step 4: Make the header show "Show all" button**

Replace the `<h2>` (line 57):

```svelte
<div class="leaderboard-header">
 <h2>{mode === 'finished' ? 'Results' : 'Leaderboard'}</h2>
 {#if hasSelection && onClearSelection}
  <button class="show-all-btn" onclick={onClearSelection}>Show all</button>
 {/if}
</div>
```

**Step 5: Make each `<li>` clickable with selection highlight**

On the `<li>` element (currently line 69), add `onclick` handler, `role`, and conditional selected class:

```svelte
<li
 class="participant {getStatusClass(participant.status)}"
 class:selected={hasSelection && selectedIds!.has(participant.id)}
 onclick={(e) => onToggle?.(participant.id, e.ctrlKey || e.metaKey)}
 role={onToggle ? 'button' : undefined}
 tabindex={onToggle ? 0 : undefined}
>
```

**Step 6: Add styles**

Add to the `<style>` block:

```css
.leaderboard-header {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  margin-bottom: 1rem;
}

.leaderboard-header h2 {
  color: var(--color-gold);
  margin: 0;
  font-size: var(--font-size-lg);
  font-weight: 600;
}

.show-all-btn {
  background: none;
  border: none;
  padding: 0;
  color: var(--color-text-secondary);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: color var(--transition);
}

.show-all-btn:hover {
  color: var(--color-text);
}

.participant {
  cursor: pointer;
}

.participant.selected {
  background: var(--color-surface-elevated);
}
```

Remove the existing standalone `h2` style rule since it's now scoped under `.leaderboard-header h2`.

**Step 7: Verify**

Run: `cd web && npm run check`
Expected: No type errors.

**Step 8: Commit**

```text
feat(leaderboard): add click-to-select with Show All and Escape reset
```

---

## Task 3: Race detail page — wire selection state between Leaderboard and MetroDagResults

Add the `selectedParticipantIds` state and connect the two components.

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`

**Step 1: Add selection state**

After the existing `$state` declarations (around line 36), add:

```typescript
let selectedParticipantIds = $state<Set<string>>(new Set());
```

**Step 2: Add handler function**

After the `handleRaceUpdated` function (line 229-231), add:

```typescript
function handleLeaderboardToggle(id: string, ctrlKey: boolean) {
  if (ctrlKey) {
    const next = new Set(selectedParticipantIds);
    if (next.has(id)) next.delete(id);
    else next.add(id);
    selectedParticipantIds = next;
  } else {
    if (selectedParticipantIds.size === 1 && selectedParticipantIds.has(id)) {
      selectedParticipantIds = new Set();
    } else {
      selectedParticipantIds = new Set([id]);
    }
  }
}

function clearSelection() {
  selectedParticipantIds = new Set();
}
```

**Step 3: Wire Leaderboard — finished state (line 242)**

Change:

```svelte
<Leaderboard participants={raceStore.leaderboard} {totalLayers} mode="finished" {zoneNames} />
```

To:

```svelte
<Leaderboard
 participants={raceStore.leaderboard}
 {totalLayers}
 mode="finished"
 {zoneNames}
 selectedIds={selectedParticipantIds}
 onToggle={handleLeaderboardToggle}
 onClearSelection={clearSelection}
/>
```

**Step 4: Wire Leaderboard — running state (line 256)**

Change:

```svelte
<Leaderboard participants={raceStore.leaderboard} {totalLayers} {zoneNames} />
```

To:

```svelte
<Leaderboard
 participants={raceStore.leaderboard}
 {totalLayers}
 {zoneNames}
 selectedIds={selectedParticipantIds}
 onToggle={handleLeaderboardToggle}
 onClearSelection={clearSelection}
/>
```

**Step 5: Wire MetroDagResults — running spectator view (line 380)**

Change:

```svelte
<MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} />
```

To:

```svelte
<MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} highlightIds={selectedParticipantIds} />
```

**Step 6: Wire MetroDagResults — finished view (line 384)**

Change:

```svelte
<MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} />
```

To:

```svelte
<MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} highlightIds={selectedParticipantIds} />
```

**Step 7: Reset selection on race status change**

In the existing `$effect` that tracks `raceStatus` (around line 124-136), add `clearSelection()` when race transitions:

After `previousRaceStatus = raceStatus;` (line 127), add:

```typescript
clearSelection();
```

This ensures the filter resets when the race transitions (e.g., running -> finished).

**Step 8: Verify**

Run: `cd web && npm run check`
Expected: No type errors.

**Step 9: Commit**

```text
feat(race): wire player filtering between Leaderboard and MetroDagResults
```

---

## Task 4: Verify end-to-end and run checks

**Step 1: Type check**

Run: `cd web && npm run check`
Expected: All green.

**Step 2: Lint**

Run: `cd web && npm run lint`
Expected: No new errors.

**Step 3: Format**

Run: `cd web && npm run format`

**Step 4: Manual test checklist**

If a dev server is available (`npm run dev`), verify:

- Click a player in Leaderboard -> only their path visible at full opacity on DAG, others dimmed
- Ctrl+click another player -> both paths visible
- Click the sole selected player again -> all paths restored
- "Show all" button appears in header when filter active -> click resets
- Escape key resets filter
- Leaderboard entries show subtle highlight for selected players
- Transitions are smooth (200ms opacity)

**Step 5: Final commit if format changed anything**

```text
style: format after player filtering feature
```
