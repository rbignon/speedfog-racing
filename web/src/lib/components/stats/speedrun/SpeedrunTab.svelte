<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import {
    fetchRaces,
    fetchSpeedrunOverview,
    type Race,
    type SpeedrunOverviewResponse,
  } from "$lib/api";
  import { DISCORD_URL } from "$lib/links";
  import {
    parseSpeedrunParams,
    recentRunParams,
    writeSpeedrunParams,
    type SpeedrunParams,
    type StartRun,
  } from "$lib/speedrun";
  import { loadCatalogue } from "$lib/stores/weaponsCatalogue.svelte";
  import SpeedrunBoard from "./SpeedrunBoard.svelte";
  import SpeedrunSidebar from "./SpeedrunSidebar.svelte";

  /** Opens the board's Start a run window: in Random Seed mode, or in Set
   * Seed mode on a seed ID. */
  let { startRun = null }: { startRun?: StartRun | null } = $props();

  // The tab owns its state and mirrors it into the URL, so a board can be
  // shared. `written` is the query string the tab last put there: a different
  // one is a navigation (the navbar link back to bare /speedrun), which
  // replaces the state.
  let written = untrack(() => page.url.search);
  let params = $state<SpeedrunParams>(
    untrack(() => parseSpeedrunParams(page.url.searchParams)),
  );

  $effect(() => {
    const search = page.url.search;
    if (search === written) return;
    written = search;
    params = parseSpeedrunParams(page.url.searchParams);
  });
  let overview = $state<SpeedrunOverviewResponse | null>(null);
  let races = $state<Race[]>([]);
  let error = $state<string | null>(null);

  onMount(async () => {
    // Speedrun and Set Seed races stay off /races; the side column lists the
    // active ones. A failed fetch only leaves them out.
    fetchRaces("setup,running", "speedrun,set_seed")
      .then((r) => (races = r))
      .catch((e) => console.error("Failed to fetch speedrun races:", e));
    try {
      const [data] = await Promise.all([
        fetchSpeedrunOverview(),
        loadCatalogue(),
      ]);
      overview = data;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load runs.";
    }
  });

  function update(next: SpeedrunParams) {
    params = next;
    const url = new URL(page.url);
    writeSpeedrunParams(url, next);
    written = url.search;
    goto(url, { replaceState: true, noScroll: true, keepFocus: true });
  }
</script>

<div class="speedrun">
  <section class="sr-panel game-header">
    <img class="cover" src="/screenshots/fog-gate.webp" alt="" />
    <div class="info">
      <h2 class="title">SpeedFog Racing <span class="year">[2026]</span></h2>
      <p class="series">Souls Series</p>
      <!-- .chip is the site-wide chip (app.css). -->
      <div class="chips"><span class="chip">PC</span></div>
      <div class="links">
        <a class="link" href={DISCORD_URL} target="_blank" rel="noopener"
          >Discord</a
        >
        <a class="link" href="/about">Website</a>
      </div>
    </div>
  </section>

  {#if error}
    <p class="message error">{error}</p>
  {:else if overview === null}
    <p class="message">Loading runs...</p>
  {:else}
    <div class="grid">
      <SpeedrunBoard
        categories={overview.categories}
        {params}
        onchange={update}
        {startRun}
      />
      <SpeedrunSidebar
        {overview}
        {races}
        onpick={(pool) => update(recentRunParams(params, pool))}
      />
    </div>
  {/if}
</div>

<style>
  .speedrun :global(.sr-panel) {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
  }

  .game-header {
    display: flex;
    gap: 1rem;
    margin-bottom: 1rem;
    padding: 1rem;
  }

  /* The cover spans the info column's height, as on speedrun.com: both
     share one fixed height, and the info column spreads its rows over it. */
  .cover {
    flex-shrink: 0;
    width: 88px;
    height: 120px;
    object-fit: cover;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
  }

  .info {
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    min-height: 120px;
  }

  .title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 1.6rem;
    font-weight: 700;
    letter-spacing: 0.02em;
    line-height: 1.1;
  }

  .year {
    margin-left: 0.25rem;
    color: var(--color-text-secondary);
    font-size: 1.2rem;
    font-weight: 600;
  }

  .series {
    margin: 0.25rem 0 0.45rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .chips,
  .links {
    display: flex;
    gap: 0.35rem;
  }

  .link {
    padding: 0.2rem 0.55rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    text-decoration: none;
  }

  .link:hover {
    color: var(--color-purple);
  }

  .grid {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 260px;
    gap: 1rem;
    align-items: start;
  }

  .message {
    color: var(--color-text-secondary);
  }

  .message.error {
    color: var(--color-danger);
  }

  /* On phones the parody header would take the first screen; its links live
     elsewhere (Discord in the navbar, the website is /about). */
  @media (max-width: 768px) {
    .game-header {
      display: none;
    }

    .grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
