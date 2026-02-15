# OBS Overlay Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add OBS-compatible transparent overlay pages (DAG + leaderboard) for casters, plus switch the race detail spectator view from MetroDagLive to MetroDagResults during RUNNING.

**Architecture:** Two new SvelteKit routes under an `/overlay/` layout group (no navbar/footer). Each page connects to the existing spectator WebSocket via `raceStore` and renders a single component full-viewport with transparent background. A new `LeaderboardOverlay` component is optimized for stream readability. An "OBS Overlays" modal in the race detail sidebar provides copy-able URLs for casters/organizers.

**Tech Stack:** SvelteKit 5 (runes), existing DAG components, existing `raceStore` + spectator WebSocket

---

### Task 1: Overlay Layout Group

Create a dedicated layout for `/overlay/` routes that strips the global navbar, footer, and app shell. The overlay layout only renders the page content on a transparent background.

**Files:**

- Create: `web/src/routes/overlay/+layout.svelte`

**Step 1: Create the overlay layout**

```svelte
<script lang="ts">
 import '../../app.css';
 import { onMount } from 'svelte';
 import { auth } from '$lib/stores/auth.svelte';
 import { site } from '$lib/stores/site.svelte';

 let { children } = $props();

 onMount(() => {
  auth.init();
  site.init();
 });
</script>

<div class="overlay-root">
 {@render children()}
</div>

<style>
 :global(html),
 :global(body) {
  background: transparent !important;
  margin: 0;
  padding: 0;
  overflow: hidden;
 }

 .overlay-root {
  width: 100vw;
  height: 100vh;
  background: transparent;
  overflow: hidden;
 }
</style>
```

**Step 2: Verify it renders**

Run: `cd web && npm run dev`

Navigate to `http://localhost:5173/overlay/` — should see an empty transparent page (no navbar/footer).

**Step 3: Commit**

```bash
git add web/src/routes/overlay/+layout.svelte
git commit -m "feat(web): add overlay layout group with transparent background"
```

---

### Task 2: DAG Overlay Page

Create the DAG overlay route that connects to the spectator WebSocket and renders the appropriate DAG component based on race status.

**Files:**

- Create: `web/src/routes/overlay/race/[id]/dag/+page.ts`
- Create: `web/src/routes/overlay/race/[id]/dag/+page.svelte`

**Step 1: Create the page loader**

The loader is identical to the race detail page loader. Create `web/src/routes/overlay/race/[id]/dag/+page.ts`:

```typescript
import { fetchRace } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params }) => {
  try {
    const race = await fetchRace(params.id);
    return { race };
  } catch {
    throw error(404, "Race not found");
  }
};
```

**Step 2: Create the DAG overlay page**

Create `web/src/routes/overlay/race/[id]/dag/+page.svelte`:

```svelte
<script lang="ts">
 import { raceStore } from '$lib/stores/race.svelte';
 import { MetroDagBlurred, MetroDagResults } from '$lib/dag';

 let { data } = $props();

 let raceStatus = $derived(raceStore.race?.status ?? data.race.status);
 let liveSeed = $derived(raceStore.seed);
 let totalLayers = $derived(liveSeed?.total_layers ?? data.race.seed_total_layers);
 let totalNodes = $derived(liveSeed?.total_nodes ?? data.race.seed_total_nodes);
 let totalPaths = $derived(liveSeed?.total_paths ?? data.race.seed_total_paths);

 $effect(() => {
  raceStore.connect(data.race.id);
  return () => {
   raceStore.disconnect();
  };
 });
</script>

<div class="dag-overlay">
 {#if liveSeed?.graph_json && (raceStatus === 'running' || raceStatus === 'finished')}
  <MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} />
 {:else if totalNodes && totalPaths && totalLayers}
  <MetroDagBlurred {totalLayers} {totalNodes} {totalPaths} />
 {/if}
</div>

<style>
 .dag-overlay {
  width: 100%;
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
 }
</style>
```

**Step 3: Verify it renders**

Run: `cd web && npm run dev`

Create a test race in the app, then navigate to `http://localhost:5173/overlay/race/{id}/dag`. It should show a MetroDagBlurred for non-started races or MetroDagResults for running/finished races.

**Step 4: Commit**

```bash
git add web/src/routes/overlay/race/\[id\]/dag/
git commit -m "feat(web): add DAG overlay page for OBS"
```

---

### Task 3: LeaderboardOverlay Component

Create a dedicated leaderboard component optimized for OBS overlays: transparent background, white text with strong text-shadow, player color dots, no scroll.

**Files:**

- Create: `web/src/lib/components/LeaderboardOverlay.svelte`

**Step 1: Create the component**

Create `web/src/lib/components/LeaderboardOverlay.svelte`. The component should:

- Accept props: `participants: WsParticipant[]`, `totalLayers?: number | null`, `mode?: 'running' | 'finished'`
- Display each participant as a row with: color dot (from `PLAYER_COLORS[color_index]`), display name, stats
- Running mode: show layer/totalLayers + IGT + death count
- Finished mode: show medal emoji for top 3 + IGT + death count + DNF for abandoned
- Use white text with `text-shadow: 0 2px 4px rgba(0,0,0,0.9), 0 0 8px rgba(0,0,0,0.7)` for readability
- No background, no borders, no scroll
- Use `font-family: 'JetBrains Mono', 'Fira Code', monospace` for tabular data

```svelte
<script lang="ts">
 import type { WsParticipant } from '$lib/websocket';
 import { PLAYER_COLORS } from '$lib/dag/constants';

 interface Props {
  participants: WsParticipant[];
  totalLayers?: number | null;
  mode?: 'running' | 'finished';
 }

 let { participants, totalLayers = null, mode = 'running' }: Props = $props();

 const MEDALS = ['\u{1F947}', '\u{1F948}', '\u{1F949}'];

 function playerColor(p: WsParticipant): string {
  return PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
 }

 function formatIgt(ms: number): string {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
   return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
  }
  return `${minutes}:${seconds.toString().padStart(2, '0')}`;
 }

 function displayName(p: WsParticipant): string {
  return p.twitch_display_name || p.twitch_username;
 }
</script>

<ol class="overlay-leaderboard">
 {#each participants as participant, index (participant.id)}
  {@const color = playerColor(participant)}
  {@const medal =
   mode === 'finished' && participant.status === 'finished' && index < 3
    ? MEDALS[index]
    : null}
  <li class="row">
   {#if medal}
    <span class="medal">{medal}</span>
   {:else}
    <span class="dot" style="background: {color};"></span>
   {/if}
   <span class="name">{displayName(participant)}</span>
   <span class="stats">
    {#if participant.status === 'playing'}
     <span class="layer">{participant.current_layer}{totalLayers ? `/${totalLayers}` : ''}</span>
     <span class="igt">{formatIgt(participant.igt_ms)}</span>
     {#if participant.death_count > 0}
      <span class="deaths">{participant.death_count}</span>
     {/if}
    {:else if participant.status === 'finished'}
     <span class="igt finished">{formatIgt(participant.igt_ms)}</span>
     {#if participant.death_count > 0}
      <span class="deaths">{participant.death_count}</span>
     {/if}
    {:else if participant.status === 'abandoned'}
     <span class="dnf">DNF</span>
    {:else}
     <span class="waiting">{participant.status}</span>
    {/if}
   </span>
  </li>
 {/each}
</ol>

<style>
 .overlay-leaderboard {
  list-style: none;
  padding: 0.5rem;
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 0.4rem;
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
 }

 .row {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  color: white;
  font-size: 1rem;
  text-shadow:
   0 2px 4px rgba(0, 0, 0, 0.9),
   0 0 8px rgba(0, 0, 0, 0.7);
 }

 .dot {
  width: 12px;
  height: 12px;
  border-radius: 50%;
  flex-shrink: 0;
  box-shadow: 0 0 4px rgba(0, 0, 0, 0.5);
 }

 .medal {
  width: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.1rem;
  flex-shrink: 0;
  filter: drop-shadow(0 2px 2px rgba(0, 0, 0, 0.8));
 }

 .name {
  flex: 1;
  min-width: 0;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
  font-weight: 600;
 }

 .stats {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
 }

 .layer {
  font-weight: 600;
  opacity: 0.9;
 }

 .igt {
  opacity: 0.8;
 }

 .igt.finished {
  color: #4ade80;
  opacity: 1;
 }

 .deaths {
  color: #f87171;
  opacity: 0.9;
 }

 .deaths::before {
  content: '\1F480';
  margin-right: 0.15em;
 }

 .dnf {
  color: #9ca3af;
  font-style: italic;
 }

 .waiting {
  text-transform: capitalize;
  opacity: 0.6;
 }
</style>
```

**Step 2: Commit**

```bash
git add web/src/lib/components/LeaderboardOverlay.svelte
git commit -m "feat(web): add LeaderboardOverlay component for OBS"
```

---

### Task 4: Leaderboard Overlay Page

Create the leaderboard overlay route that renders the `LeaderboardOverlay` component.

**Files:**

- Create: `web/src/routes/overlay/race/[id]/leaderboard/+page.ts`
- Create: `web/src/routes/overlay/race/[id]/leaderboard/+page.svelte`

**Step 1: Create the page loader**

Create `web/src/routes/overlay/race/[id]/leaderboard/+page.ts` (same pattern as DAG):

```typescript
import { fetchRace } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params }) => {
  try {
    const race = await fetchRace(params.id);
    return { race };
  } catch {
    throw error(404, "Race not found");
  }
};
```

**Step 2: Create the leaderboard overlay page**

Create `web/src/routes/overlay/race/[id]/leaderboard/+page.svelte`:

```svelte
<script lang="ts">
 import { raceStore } from '$lib/stores/race.svelte';
 import LeaderboardOverlay from '$lib/components/LeaderboardOverlay.svelte';

 let { data } = $props();

 let raceStatus = $derived(raceStore.race?.status ?? data.race.status);
 let liveSeed = $derived(raceStore.seed);
 let totalLayers = $derived(liveSeed?.total_layers ?? data.race.seed_total_layers);
 let mode = $derived<'running' | 'finished'>(raceStatus === 'finished' ? 'finished' : 'running');

 $effect(() => {
  raceStore.connect(data.race.id);
  return () => {
   raceStore.disconnect();
  };
 });
</script>

<div class="leaderboard-overlay">
 <LeaderboardOverlay participants={raceStore.leaderboard} {totalLayers} {mode} />
</div>

<style>
 .leaderboard-overlay {
  width: 100%;
  height: 100vh;
  display: flex;
  flex-direction: column;
  justify-content: flex-start;
  padding: 1rem;
  box-sizing: border-box;
 }
</style>
```

**Step 3: Verify it renders**

Navigate to `http://localhost:5173/overlay/race/{id}/leaderboard`. Should show participant names with color dots and stats on a transparent background.

**Step 4: Commit**

```bash
git add web/src/routes/overlay/race/\[id\]/leaderboard/
git commit -m "feat(web): add leaderboard overlay page for OBS"
```

---

### Task 5: OBS Overlay Modal

Add a modal in the race detail sidebar that shows the two overlay URLs with copy buttons. Visible to casters and the organizer.

**Files:**

- Create: `web/src/lib/components/ObsOverlayModal.svelte`
- Modify: `web/src/routes/race/[id]/+page.svelte`

**Step 1: Create the modal component**

Create `web/src/lib/components/ObsOverlayModal.svelte`:

```svelte
<script lang="ts">
 interface Props {
  raceId: string;
  onClose: () => void;
 }

 let { raceId, onClose }: Props = $props();

 let dagCopied = $state(false);
 let lbCopied = $state(false);

 let dagUrl = $derived(
  typeof window !== 'undefined'
   ? `${window.location.origin}/overlay/race/${raceId}/dag`
   : ''
 );

 let lbUrl = $derived(
  typeof window !== 'undefined'
   ? `${window.location.origin}/overlay/race/${raceId}/leaderboard`
   : ''
 );

 async function copyUrl(url: string, which: 'dag' | 'lb') {
  await navigator.clipboard.writeText(url);
  if (which === 'dag') {
   dagCopied = true;
   setTimeout(() => (dagCopied = false), 2000);
  } else {
   lbCopied = true;
   setTimeout(() => (lbCopied = false), 2000);
  }
 }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="modal-backdrop" onclick={onClose} onkeydown={(e) => e.key === 'Escape' && onClose()}>
 <!-- svelte-ignore a11y_no_static_element_interactions -->
 <div class="modal" onclick|stopPropagation>
  <div class="modal-header">
   <h2>OBS Overlays</h2>
   <button class="close-btn" onclick={onClose}>&times;</button>
  </div>

  <p class="description">
   Add these as <strong>Browser Sources</strong> in OBS with transparent background.
  </p>

  <div class="overlay-section">
   <h3>DAG</h3>
   <p class="size-hint">Recommended size: 800 &times; 600</p>
   <div class="url-row">
    <input type="text" readonly value={dagUrl} class="url-input" />
    <button class="copy-btn" onclick={() => copyUrl(dagUrl, 'dag')}>
     {dagCopied ? 'Copied!' : 'Copy'}
    </button>
   </div>
  </div>

  <div class="overlay-section">
   <h3>Leaderboard</h3>
   <p class="size-hint">Recommended size: 400 &times; 800</p>
   <div class="url-row">
    <input type="text" readonly value={lbUrl} class="url-input" />
    <button class="copy-btn" onclick={() => copyUrl(lbUrl, 'lb')}>
     {lbCopied ? 'Copied!' : 'Copy'}
    </button>
   </div>
  </div>
 </div>
</div>

<style>
 .modal-backdrop {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.6);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
 }

 .modal {
  background: var(--color-surface);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-lg);
  padding: 1.5rem;
  max-width: 500px;
  width: 90%;
 }

 .modal-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
 }

 .modal-header h2 {
  margin: 0;
  color: var(--color-gold);
  font-size: var(--font-size-lg);
 }

 .close-btn {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  font-size: 1.5rem;
  cursor: pointer;
  padding: 0;
  line-height: 1;
 }

 .close-btn:hover {
  color: var(--color-text);
 }

 .description {
  color: var(--color-text-secondary);
  font-size: var(--font-size-sm);
  margin: 0 0 1rem 0;
 }

 .overlay-section {
  margin-bottom: 1rem;
 }

 .overlay-section:last-child {
  margin-bottom: 0;
 }

 .overlay-section h3 {
  margin: 0 0 0.25rem 0;
  font-size: var(--font-size-base);
  color: var(--color-text);
 }

 .size-hint {
  margin: 0 0 0.5rem 0;
  font-size: var(--font-size-sm);
  color: var(--color-text-disabled);
 }

 .url-row {
  display: flex;
  gap: 0.5rem;
 }

 .url-input {
  flex: 1;
  padding: 0.5rem 0.75rem;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: var(--font-size-sm);
  min-width: 0;
 }

 .copy-btn {
  padding: 0.5rem 1rem;
  background: var(--color-purple);
  color: white;
  border: none;
  border-radius: var(--radius-sm);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  cursor: pointer;
  white-space: nowrap;
  transition: background var(--transition);
 }

 .copy-btn:hover {
  background: var(--color-purple-hover, #7c3aed);
 }
</style>
```

**Step 2: Add the "OBS Overlays" button and modal to the race detail page**

Modify `web/src/routes/race/[id]/+page.svelte`:

1. Add import at top (after existing imports):

```typescript
import ObsOverlayModal from "$lib/components/ObsOverlayModal.svelte";
```

2. Add state and derived caster check (after the `isOrganizer` derived on line 138):

```typescript
let isCaster = $derived(
  auth.user
    ? initialRace.casters.some((c) => c.user.id === auth.user?.id)
    : false,
);
let showObsModal = $state(false);
```

3. Add the OBS Overlays button in the sidebar, just before the `<div class="sidebar-footer">` (line 290). Place it in all three status branches (finished, running, draft/open) — OR more simply, add it once right before `sidebar-footer` since it should appear regardless of race status:

Insert before line 290 (`<div class="sidebar-footer">`):

```svelte
  {#if isOrganizer || isCaster}
   <button class="obs-overlay-btn" onclick={() => (showObsModal = true)}>
    OBS Overlays
   </button>
  {/if}
```

4. Add the modal at the end of the component, just before `</div>` closing `.race-page` (line 388):

```svelte
{#if showObsModal}
 <ObsOverlayModal raceId={initialRace.id} onClose={() => (showObsModal = false)} />
{/if}
```

5. Add button style in `<style>` section:

```css
.obs-overlay-btn {
  width: 100%;
  padding: 0.5rem;
  margin-top: 0.75rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text-secondary);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: all var(--transition);
}

.obs-overlay-btn:hover {
  border-color: var(--color-purple);
  color: var(--color-purple);
}
```

**Step 3: Verify**

Log in as a caster or organizer. Navigate to a race detail page. The "OBS Overlays" button should appear in the sidebar. Clicking it opens the modal with two URLs and copy buttons.

**Step 4: Commit**

```bash
git add web/src/lib/components/ObsOverlayModal.svelte web/src/routes/race/\[id\]/+page.svelte
git commit -m "feat(web): add OBS overlay modal with copy-able URLs for casters"
```

---

### Task 6: Switch Race Detail Spectator View to MetroDagResults

Change the race detail page to show `MetroDagResults` (colored trails) instead of `MetroDagLive` for spectators/casters during RUNNING races.

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte:317-326`

**Step 1: Replace MetroDagLive with MetroDagResults for spectators**

In `web/src/routes/race/[id]/+page.svelte`, find the RUNNING status DAG block (lines 317-326):

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
```

Replace the `{:else}` branch to use `MetroDagResults` instead of `MetroDagLive`:

```svelte
 {#if liveSeed?.graph_json && raceStatus === 'running'}
  {#if myWsParticipantId}
   <MetroDagProgressive
    graphJson={liveSeed.graph_json}
    participants={raceStore.participants}
    myParticipantId={myWsParticipantId}
   />
  {:else}
   <MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} />
  {/if}
```

Note: `MetroDagResults` takes `participants` as the leaderboard-sorted array (same as the finished state on line 329), while `MetroDagLive` used the raw `raceStore.participants`. Use `raceStore.leaderboard` for consistency.

**Step 2: Clean up unused import**

The `MetroDagLive` import on line 17 is no longer used in this file. Remove it from the destructured import:

```typescript
// Before:
import {
  MetroDag,
  MetroDagBlurred,
  MetroDagLive,
  MetroDagProgressive,
  MetroDagResults,
} from "$lib/dag";

// After:
import {
  MetroDag,
  MetroDagBlurred,
  MetroDagProgressive,
  MetroDagResults,
} from "$lib/dag";
```

Do NOT remove `MetroDagLive` from `web/src/lib/dag/index.ts` — keep it available in the codebase for potential future use.

**Step 3: Run type check**

Run: `cd web && npm run check`

Expected: no errors.

**Step 4: Commit**

```bash
git add web/src/routes/race/\[id\]/+page.svelte
git commit -m "feat(web): switch spectator RUNNING view from MetroDagLive to MetroDagResults"
```

---

### Task 7: Type Check and Visual Verification

Run the full type checker and do a visual verification of all new pages.

**Files:** None (verification only)

**Step 1: Run type check**

Run: `cd web && npm run check`

Expected: no type errors.

**Step 2: Run linter**

Run: `cd web && npm run lint`

Fix any issues that come up.

**Step 3: Visual smoke test**

Start the dev server (`cd web && npm run dev`) and the backend server (`cd server && uv run speedfog-racing`). Test:

1. Navigate to a race detail page as organizer → "OBS Overlays" button visible in sidebar
2. Click it → modal opens with two URLs
3. Copy a URL → clipboard works
4. Open DAG overlay URL → shows MetroDagBlurred (for non-started race)
5. Open leaderboard overlay URL → shows participant list on transparent background
6. If a running/finished race is available, verify MetroDagResults shows on both the overlay and the race detail page (for non-participant spectators)

**Step 4: Commit any fixes**

```bash
git add -u
git commit -m "fix(web): address lint/type issues in overlay feature"
```
