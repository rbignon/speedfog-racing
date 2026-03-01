# Solo OBS Overlay — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a DAG OBS overlay for Solo (training) sessions, reusing the existing MetroDagFull component and adapting ObsOverlayModal.

**Architecture:** New route `/overlay/training/[id]/dag/` connects to the training spectator WebSocket and renders MetroDagFull. The existing ObsOverlayModal gains a `mode` prop to hide the leaderboard section and generate training URLs. A button in the solo session detail page opens the modal.

**Tech Stack:** SvelteKit 5 (runes), TypeScript, existing WebSocket infrastructure

---

## Task 1: Create the overlay DAG route data loader

**Files:**

- Create: `web/src/routes/overlay/training/[id]/dag/+page.ts`

This mirrors the race overlay loader at `web/src/routes/overlay/race/[id]/dag/+page.ts` but uses `fetchTrainingSession`.

```typescript
import { fetchTrainingSession } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params }) => {
  try {
    const session = await fetchTrainingSession(params.id);
    return { session };
  } catch {
    throw error(404, "Training session not found");
  }
};
```

Commit: `git commit -m "feat: add training DAG overlay data loader"`

---

## Task 2: Create the overlay DAG page

**Files:**

- Create: `web/src/routes/overlay/training/[id]/dag/+page.svelte`

Mirrors `web/src/routes/overlay/race/[id]/dag/+page.svelte` but uses `trainingStore` instead of `raceStore`. The training store exposes `participant` (singular) which we wrap in an array for `MetroDagFull`.

```svelte
<script lang="ts">
 import { untrack } from 'svelte';
 import { page } from '$app/state';
 import { auth } from '$lib/stores/auth.svelte';
 import { trainingStore } from '$lib/stores/training.svelte';
 import { getEffectiveLocale } from '$lib/stores/locale.svelte';
 import { MetroDagFull } from '$lib/dag';

 let { data } = $props();

 let liveRace = $derived(trainingStore.race);
 let liveSeed = $derived(trainingStore.seed);
 let liveParticipant = $derived(trainingStore.participant);

 let sessionStatus = $derived(liveRace?.status ?? data.session.status);
 let graphJson = $derived(liveSeed?.graph_json ?? data.session.graph_json ?? null);

 let dagParticipants = $derived.by(() => {
  if (liveParticipant) return [liveParticipant];
  if (!data.session.progress_nodes || data.session.progress_nodes.length === 0) return [];
  return [
   {
    id: data.session.id,
    twitch_username: data.session.user?.twitch_username ?? '',
    twitch_display_name: data.session.user?.twitch_display_name ?? null,
    status: data.session.status === 'active' ? ('playing' as const) : data.session.status,
    current_zone:
     data.session.progress_nodes[data.session.progress_nodes.length - 1]?.node_id ?? null,
    current_layer: data.session.current_layer ?? 0,
    igt_ms: data.session.igt_ms,
    death_count: data.session.death_count,
    color_index: 0,
    mod_connected: false,
    zone_history: data.session.progress_nodes
   }
  ];
 });

 let follow = $derived(page.url.searchParams.get('follow') === 'true');
 let maxLayers = $derived(
  (() => {
   const raw = page.url.searchParams.get('maxLayers');
   if (raw === null || raw === '') return 5;
   const n = parseInt(raw, 10);
   return isNaN(n) || n < 3 ? 5 : n;
  })()
 );

 $effect(() => {
  if (!auth.initialized) return;

  const locale = untrack(() => getEffectiveLocale());
  trainingStore.connect(data.session.id, locale);
  return () => {
   trainingStore.disconnect();
  };
 });
</script>

<div class="dag-overlay">
 {#if graphJson && dagParticipants.length > 0}
  <MetroDagFull
   {graphJson}
   participants={dagParticipants}
   raceStatus={sessionStatus === 'active' ? 'running' : sessionStatus}
   transparent
   {follow}
   {maxLayers}
   showLiveDots
  />
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

Key differences from the race overlay:

- Uses `trainingStore` (single participant) instead of `raceStore` (multi-participant)
- Wraps single participant in array via `dagParticipants`
- Falls back to static session data if WS not connected (same pattern as `training/[id]/+page.svelte`)
- Maps training status `active` to `running` for `MetroDagFull`'s `raceStatus` prop
- No `anonymous`/`setup` state (training sessions don't have a setup phase)

Verify: `cd web && npm run check` (PASS, no type errors)

Commit: `git commit -m "feat: add training DAG overlay page"`

---

## Task 3: Adapt ObsOverlayModal with mode prop

**Files:**

- Modify: `web/src/lib/components/ObsOverlayModal.svelte`

Update the `Props` interface to accept either a `raceId` or `sessionId`, plus `mode`:

```typescript
interface Props {
  mode?: "race" | "training";
  raceId?: string;
  sessionId?: string;
  onClose: () => void;
}

let { mode = "race", raceId, sessionId, onClose }: Props = $props();

let entityId = $derived(mode === "training" ? sessionId! : raceId!);
```

Update `dagUrl` to use the correct path based on mode:

```typescript
let dagUrl = $derived(
  typeof window !== "undefined"
    ? `${window.location.origin}/overlay/${mode === "training" ? "training" : "race"}/${entityId}/dag${dagFollow ? `?follow=true${dagMaxLayers !== 5 ? `&maxLayers=${dagMaxLayers}` : ""}` : ""}`
    : "",
);
```

In the template, wrap the leaderboard section with `{#if mode !== 'training'}`:

```svelte
{#if mode !== 'training'}
 <div class="overlay-section">
  <h3>Leaderboard</h3>
  <!-- ... existing leaderboard section unchanged ... -->
 </div>
{/if}
```

The existing race detail call `<ObsOverlayModal raceId={initialRace.id} .../>` continues to work unchanged (mode defaults to `'race'`).

Verify: `cd web && npm run check` (PASS)

Commit: `git commit -m "feat: add mode prop to ObsOverlayModal for training support"`

---

## Task 4: Add OBS Overlay button to solo session page

**Files:**

- Modify: `web/src/routes/training/[id]/+page.svelte`

Add `ObsOverlayModal` import alongside existing imports:

```typescript
import ObsOverlayModal from "$lib/components/ObsOverlayModal.svelte";
```

Add state variable:

```typescript
let showObsModal = $state(false);
```

In the `{#if isOwner}` block, add the button (visible regardless of session status):

```svelte
{#if isOwner}
 <div class="actions">
  <button class="btn btn-secondary" onclick={() => (showObsModal = true)}>
   OBS Overlay
  </button>
  {#if status === 'active'}
   <button class="btn btn-secondary" disabled={downloading} onclick={handleDownload}>
    {downloading ? 'Preparing...' : 'Download Pack'}
   </button>
  {/if}

  {#if status === 'active'}
   <button class="btn btn-danger-outline" onclick={() => (showAbandonConfirm = true)}>
    Abandon
   </button>
  {/if}
 </div>
{/if}
```

After the existing `ConfirmModal`, add:

```svelte
{#if showObsModal}
 <ObsOverlayModal
  mode="training"
  sessionId={sessionId}
  onClose={() => (showObsModal = false)}
 />
{/if}
```

Verify: `cd web && npm run check` (PASS)

Commit: `git commit -m "feat: add OBS Overlay button to solo session page"`

---

## Task 5: Manual testing

1. Start dev server: `cd web && npm run dev`
2. Navigate to a training session, click "OBS Overlay" — verify modal opens with DAG only (no leaderboard)
3. Copy URL, open in new tab — verify transparent background and DAG rendering
4. Test `?follow=true` and `?follow=true&maxLayers=8` query params
5. Navigate to a race detail page — verify modal still shows both DAG and Leaderboard sections
6. Run `cd web && npm run check` and `npm run lint` — both PASS
