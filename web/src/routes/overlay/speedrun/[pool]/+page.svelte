<script lang="ts">
  import { page } from "$app/state";
  import { fetchSpeedrunBoard, type SpeedrunRun } from "$lib/api";
  import {
    parseSpeedrunOverlayParams,
    speedrunOverlayRows,
  } from "$lib/speedrun";
  import { formatIgt } from "$lib/utils/training";
  import SpeedrunPlayer from "$lib/components/stats/speedrun/SpeedrunPlayer.svelte";
  import SpeedrunTrophy from "$lib/components/stats/speedrun/SpeedrunTrophy.svelte";

  // The board is cached server side for minutes, so polling faster buys nothing.
  const REFRESH_MS = 5 * 60_000;
  // Until a first board arrives (OBS started during a network blip or a
  // server restart), retry sooner than the refresh.
  const RETRY_MS = 30_000;
  const PAGE_MS = 6_000;
  const FADE_MS = 400;

  let options = $derived(parseSpeedrunOverlayParams(page.url.searchParams));
  let runs = $state<SpeedrunRun[]>([]);
  let rows = $derived(speedrunOverlayRows(runs, options));
  let pageIndex = $state(0);
  let fading = $state(false);

  let current = $derived(
    rows.pages.length > 0 ? rows.pages[pageIndex % rows.pages.length] : [],
  );
  // A short last page keeps its empty slots, so the pinned row never moves.
  let blanks = $derived((rows.pages[0]?.length ?? 0) - current.length);
  // A number, so a refetch of the same board does not restart the paging.
  let pageCount = $derived(rows.pages.length);

  $effect(() => {
    const pool = page.params.pool ?? "";
    const { sub, types } = options;
    let cancelled = false;
    let retry: ReturnType<typeof setTimeout> | undefined;
    const load = async () => {
      try {
        const board = await fetchSpeedrunBoard(pool, {
          deathless: sub === "deathless",
          types,
          obsolete: false,
        });
        if (!cancelled) runs = board.runs;
      } catch {
        // Keep the last board; an unknown category simply shows nothing.
        if (!cancelled && runs.length === 0) {
          retry = setTimeout(load, RETRY_MS);
        }
      }
    };
    load();
    const timer = setInterval(load, REFRESH_MS);
    return () => {
      cancelled = true;
      clearInterval(timer);
      clearTimeout(retry);
    };
  });

  $effect(() => {
    const count = pageCount;
    if (count < 2) return;
    let fade: ReturnType<typeof setTimeout> | undefined;
    const timer = setInterval(() => {
      fading = true;
      fade = setTimeout(() => {
        pageIndex = (pageIndex + 1) % count;
        fading = false;
      }, FADE_MS);
    }, PAGE_MS);
    return () => {
      clearInterval(timer);
      clearTimeout(fade);
      fading = false;
    };
  });
</script>

{#snippet row(run: SpeedrunRun)}
  {@const self = run.user.id === rows.selfId}
  <li class="row" class:self>
    <span class="rank">
      {#if run.rank !== null && run.rank <= 3}
        <SpeedrunTrophy place={run.rank} />
      {:else}
        {run.rank}.
      {/if}
    </span>
    <span class="player"><SpeedrunPlayer user={run.user} /></span>
    <span class="time">{formatIgt(run.igt_ms)}</span>
  </li>
{/snippet}

<div class="speedrun-overlay">
  {#if runs.length > 0}
    <ol class="rows">
      {#each rows.top as run (run.user.id)}
        {@render row(run)}
      {/each}
    </ol>
    {#if current.length > 0}
      <ol
        class="rows cycle"
        class:fading
        style:transition-duration="{FADE_MS}ms"
      >
        {#each current as run (run.user.id)}
          {@render row(run)}
        {/each}
        {#each { length: blanks }, i (i)}
          <li class="row" aria-hidden="true"></li>
        {/each}
      </ol>
    {/if}
    {#if rows.self}
      <ol class="rows pinned">
        {@render row(rows.self)}
      </ol>
    {/if}
  {/if}
</div>

<style>
  .speedrun-overlay {
    width: 100%;
    height: 100vh;
    padding: 1rem;
    box-sizing: border-box;
  }

  .rows {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .cycle {
    transition: opacity;
  }

  .cycle.fading {
    opacity: 0;
  }

  .pinned {
    margin-top: 0.6rem;
  }

  .row {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    height: 1.75rem;
    color: white;
    font-size: 1rem;
    text-shadow:
      0 2px 4px rgba(0, 0, 0, 0.9),
      0 0 8px rgba(0, 0, 0, 0.7);
  }

  .rank {
    display: flex;
    justify-content: flex-end;
    width: 3ch;
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.85em;
    opacity: 0.8;
  }

  .rank :global(.sr-trophy) {
    filter: drop-shadow(0 1px 2px rgba(0, 0, 0, 0.9));
  }

  /* Gradient names are clipped text, which a text shadow would cover. */
  .player {
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-shadow: none;
    filter: drop-shadow(0 2px 3px rgba(0, 0, 0, 0.95));
  }

  .time {
    flex-shrink: 0;
    font-family: var(--font-mono);
  }

  .self .time {
    color: var(--color-gold);
  }
</style>
