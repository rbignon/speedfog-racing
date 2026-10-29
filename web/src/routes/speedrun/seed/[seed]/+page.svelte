<script lang="ts">
  import { untrack } from "svelte";
  import { auth } from "$lib/stores/auth.svelte";
  import { fetchSpeedrunSeed, type SpeedrunSeed } from "$lib/api";
  import type { WsParticipant } from "$lib/websocket";
  import Leaderboard from "$lib/components/Leaderboard.svelte";
  import PoolSettingsCard from "$lib/components/PoolSettingsCard.svelte";
  import ShareButtons from "$lib/components/ShareButtons.svelte";
  import SidebarHandle from "$lib/components/SidebarHandle.svelte";
  import SeedAdminControls from "$lib/components/stats/speedrun/SeedAdminControls.svelte";
  import SeedReplayCard from "$lib/components/stats/speedrun/SeedReplayCard.svelte";
  import SeedStatusChip from "$lib/components/stats/speedrun/SeedStatusChip.svelte";
  import { MetroDagFull } from "$lib/dag";
  import { formatIgt } from "$lib/dag/popupData";
  import { RaceReplay } from "$lib/replay";
  import { speedrunRaceHref } from "$lib/speedrun";

  let { data } = $props();

  // The run the page was opened on is ticked, so the map shows its path
  // alone; a run that is not listed ticks nothing, as on race pages.
  function openedSelection(s: SpeedrunSeed, run: string | null): Set<string> {
    return run !== null && s.runs.some((r) => r.run_id === run)
      ? new Set([run])
      : new Set();
  }

  // untrack: initial snapshot only; the $effect below follows navigation.
  let seed: SpeedrunSeed = $state(untrack(() => data.seed));
  let selectedIds = $state<Set<string>>(
    untrack(() => openedSelection(data.seed, data.run)),
  );
  let dagView = $state<"map" | "replay">("map");
  let sidebarCollapsed = $state(false);

  $effect(() => {
    seed = data.seed;
    selectedIds = openedSelection(data.seed, data.run);
  });

  // Every run on the seed as a finished runner, in time order: the list's
  // rows and the map's paths.
  let participants: WsParticipant[] = $derived(
    seed.runs.map((run, i) => ({
      id: run.run_id,
      twitch_username: run.user.twitch_username,
      twitch_display_name: run.user.twitch_display_name,
      status: "finished",
      current_zone:
        run.zone_history?.[run.zone_history.length - 1]?.node_id ?? null,
      current_layer: 0,
      igt_ms: run.igt_ms,
      death_count: run.deaths,
      color_index: i,
      mod_connected: false,
      zone_history: run.zone_history,
      equipped_badge_id: run.user.equipped_badge_id ?? null,
      equipped_name_template_id: run.user.equipped_name_template_id ?? null,
    })),
  );
  let runKinds = $derived(
    Object.fromEntries(
      seed.runs.map((r) => [r.run_id, r.blind ? "blind" : "replay"] as const),
    ),
  );
  let replays = $derived(seed.runs.filter((r) => !r.blind).length);

  // The race page's selection: a click ticks one run alone (or clears it),
  // Ctrl+click adds or removes one. The set is replaced, never mutated.
  function handleToggle(id: string, ctrlKey: boolean) {
    if (ctrlKey) {
      selectedIds = selectedIds.has(id)
        ? new Set([...selectedIds].filter((x) => x !== id))
        : new Set([...selectedIds, id]);
    } else if (selectedIds.size === 1 && selectedIds.has(id)) {
      selectedIds = new Set();
    } else {
      selectedIds = new Set([id]);
    }
  }

  function clearSelection() {
    selectedIds = new Set();
  }

  // After a protection or an admin exclusion: the status chip, the kept
  // reasons and the viewer block follow. A failed reload keeps the page as
  // it is; the action itself went through.
  async function reload() {
    try {
      seed = await fetchSpeedrunSeed(seed.seed_number);
    } catch {
      // Nothing to do: the next visit loads the new state.
    }
  }

  function formatDay(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }
</script>

<svelte:head>
  <title>Seed {seed.seed_number} - SpeedFog Racing</title>
</svelte:head>

<div class="seed-page">
  {#if seed.public}
    <aside class="sidebar" class:collapsed={sidebarCollapsed}>
      <SidebarHandle
        collapsed={sidebarCollapsed}
        onToggle={() => (sidebarCollapsed = !sidebarCollapsed)}
      />
      <div class="sidebar-section">
        <div class="leaderboard-header">
          <h2>Runs on this seed</h2>
        </div>
        {#if participants.length === 0}
          <p class="empty">No ranked run on this seed yet.</p>
        {:else}
          <Leaderboard
            {participants}
            totalLayers={seed.total_layers}
            mode="finished"
            showRunDetails
            {runKinds}
            {selectedIds}
            onToggle={handleToggle}
            onClearSelection={clearSelection}
          />
        {/if}
      </div>
    </aside>
  {/if}

  <main class="main-content">
    <div class="seed-header-wrapper">
      <header class="seed-header">
        <div class="seed-title">
          <h1>Seed {seed.seed_number}</h1>
          <p class="origin">
            {seed.category_name}
            {#if seed.origin}
              · first played {#if seed.origin.race_id}in <a
                  href={speedrunRaceHref({
                    race_id: seed.origin.race_id,
                    daily_date: seed.origin.daily_date,
                  })}>{seed.origin.race_name}</a
                >{:else}solo{/if} on {formatDay(seed.origin.played_at)}
            {/if}
          </p>
        </div>
        <div class="header-right">
          <ShareButtons />
          <SeedStatusChip {seed} />
        </div>
      </header>
    </div>

    {#if seed.public}
      <SeedReplayCard {seed} onprotect={reload} />

      {#if seed.graph_json}
        {#if participants.length > 0}
          <div class="dag-view-toggle">
            <button
              class="toggle-btn"
              class:active={dagView === "map"}
              onclick={() => (dagView = "map")}>Map</button
            >
            <button
              class="toggle-btn"
              class:active={dagView === "replay"}
              onclick={() => (dagView = "replay")}>Replay</button
            >
          </div>
        {/if}
        <div class="dag-wrapper">
          {#if dagView === "map" || participants.length === 0}
            <MetroDagFull
              graphJson={seed.graph_json}
              {participants}
              raceStatus="finished"
              highlightIds={selectedIds}
              layerGaps
            />
          {:else}
            <RaceReplay
              graphJson={seed.graph_json}
              {participants}
              highlightIds={selectedIds}
            />
          {/if}
        </div>
      {/if}
    {:else}
      <div class="dag-placeholder">
        <p class="dag-note">
          This seed's map opens once every blind run on it is over.
        </p>
      </div>
    {/if}

    {#if auth.isAdmin}
      <SeedAdminControls {seed} onchange={reload} />
    {/if}

    {#if seed.public}
      <div class="seed-stats">
        <div class="info-grid">
          {#if seed.stats.best_igt_ms !== null}
            <div class="info-item">
              <span class="label">Best Time</span>
              <span class="value">{formatIgt(seed.stats.best_igt_ms)}</span>
            </div>
          {/if}
          {#if seed.stats.median_igt_ms !== null}
            <div class="info-item">
              <span class="label">Median Time</span>
              <span class="value">{formatIgt(seed.stats.median_igt_ms)}</span>
            </div>
          {/if}
          <div class="info-item">
            <span class="label">Runs</span>
            <span class="value"
              >{seed.stats.runs}{#if replays > 0}
                ({replays} {replays === 1 ? "replay" : "replays"}){/if}</span
            >
          </div>
          <div class="info-item">
            <span class="label">Players</span>
            <span class="value">{seed.stats.players}</span>
          </div>
        </div>
      </div>

      {#if seed.pool_config}
        <PoolSettingsCard
          poolName={seed.category.split("@")[0]}
          poolConfig={seed.pool_config}
        />
      {/if}
    {/if}
  </main>
</div>

<style>
  /* The race page's finished layout: results rail, then the main column. */
  .seed-page {
    display: flex;
    flex: 1;
    min-height: 0;
  }

  .sidebar {
    position: relative;
    width: 280px;
    background: var(--color-surface);
    border-right: 1px solid var(--color-border);
    padding: 1.5rem;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    min-height: 0;
  }

  /* Desktop only, as on the race page: on mobile the rail stacks above the
     page and the handle is hidden. */
  @media not all and (max-width: 768px) {
    .sidebar {
      overflow-x: clip;
      transition:
        width var(--transition),
        padding var(--transition);
    }

    .sidebar > :global(:not(.sidebar-handle)) {
      min-width: calc(280px - 3rem - 1px);
    }

    .sidebar.collapsed {
      width: 44px;
      padding: 0;
    }

    .sidebar.collapsed > :global(:not(.sidebar-handle)) {
      display: none;
    }
  }

  .sidebar-section {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }

  .sidebar-section h2 {
    color: var(--color-gold);
    margin: 0;
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }

  .leaderboard-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 1rem;
  }

  .empty {
    color: var(--color-text-disabled);
    font-style: italic;
    margin: 0;
  }

  .main-content {
    flex: 1;
    min-width: 0;
    padding: 2rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    overflow-y: auto;
  }

  /* The header stacks on its own width, not the viewport's: the rail eats
     into it. */
  .seed-header-wrapper {
    container: seed-header / inline-size;
  }

  .seed-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
  }

  .seed-title {
    flex: 0 1 auto;
    min-width: 0;
  }

  .seed-header h1 {
    margin: 0;
    color: var(--color-text);
    font-weight: 600;
    letter-spacing: 0.03em;
    overflow-wrap: anywhere;
  }

  .origin {
    margin: 0.25rem 0 0 0;
    color: var(--color-text-disabled);
  }

  .origin a {
    color: var(--color-purple);
    text-decoration: none;
  }

  .origin a:hover {
    color: var(--color-purple-hover);
  }

  .header-right {
    flex: 1 1 0;
    display: flex;
    flex-wrap: wrap;
    justify-content: flex-end;
    align-items: center;
    gap: 0.75rem;
  }

  @container seed-header (max-width: 40rem) {
    .seed-header {
      flex-direction: column;
      gap: 0.5rem;
    }

    .header-right {
      flex: none;
      justify-content: flex-start;
    }

    /* Left-aligned, the chip's tooltip opens rightward instead of spilling
       off the left edge. */
    .header-right :global(.seed-tip) {
      left: 0;
      right: auto;
    }
  }

  .dag-view-toggle {
    display: flex;
    gap: 0.25rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 0.25rem;
    width: fit-content;
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

  .dag-wrapper {
    position: relative;
  }

  :global(.seed-page .zoomable-container) {
    min-height: 400px;
  }

  /* The graph canvas itself, never a bare `svg` descendant (see the race
     page). */
  :global(.seed-page .zoomable-svg) {
    min-height: 400px;
  }

  .dag-placeholder {
    background: var(--color-surface);
    border: 2px dashed var(--color-border);
    border-radius: var(--radius-lg);
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 400px;
    padding: 1rem;
    text-align: center;
  }

  .dag-note {
    color: var(--color-text-disabled);
    font-size: 0.85rem;
    font-style: italic;
    margin: 0;
  }

  /* The race page's stats row (RaceStats). */
  .seed-stats {
    background: var(--color-surface);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
  }

  .info-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
    gap: 1rem;
  }

  .info-item {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .label {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
  }

  .value {
    font-weight: 500;
    font-family: var(--font-mono);
  }

  @media (max-width: 768px) {
    .seed-page {
      flex-direction: column;
      flex: initial;
    }

    .sidebar {
      width: 100%;
      border-right: none;
      border-bottom: 1px solid var(--color-border);
      padding: 1rem;
    }

    .main-content {
      padding: 1rem;
      overflow-y: visible;
    }

    .seed-header h1 {
      font-size: var(--font-size-xl);
    }

    .info-grid {
      grid-template-columns: 1fr 1fr;
    }
  }
</style>
