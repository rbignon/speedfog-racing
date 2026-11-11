<script lang="ts">
  import { goto } from "$app/navigation";
  import type { SpeedrunRun } from "$lib/api";
  import {
    RUN_KIND_TITLES,
    speedrunAgo,
    speedrunSeedHref,
  } from "$lib/speedrun";
  import { getWeaponName } from "$lib/stores/weaponsCatalogue.svelte";
  import { formatCombo } from "$lib/weapons";
  import SpeedrunPlayer from "./SpeedrunPlayer.svelte";
  import SpeedrunTime from "./SpeedrunTime.svelte";
  import SpeedrunTrophy from "./SpeedrunTrophy.svelte";

  // The parent keys this component by board, so `shown` resets per board.
  const PAGE_SIZE = 100;

  let { runs, showRun = false }: { runs: SpeedrunRun[]; showRun?: boolean } =
    $props();

  let shown = $state(PAGE_SIZE);
  // Relative dates are computed once per board, like a page load would.
  const now = Date.now();
  // Every cell is a link to the run's seed page, the player's around the
  // name, so the row acts as one link (a modified or middle click opens a
  // new tab); only the seed cell's link is in the tab order, the others still
  // read out with their cell. On the rest (the player cell's padding, the
  // badge, the race bubble), a plain click opens the run too, unless it ended
  // a text selection; a modified click there does nothing rather than open
  // the run in this tab.
  function openSeed(e: MouseEvent, href: string) {
    if ((e.target as Element).closest("a, button")) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    if (window.getSelection()?.toString()) return;
    void goto(href);
  }
  let visible = $derived(runs.slice(0, shown));
</script>

<!-- Rows are links to a seed page whose load is heavy (its map): preloading
     on hover would fetch one per row the pointer crosses. -->
<div class="table-wrap" data-sveltekit-preload-data="tap">
  <table class="sr-table">
    <thead>
      <tr>
        <th>#</th>
        <th class="left">Player</th>
        <th>Time</th>
        {#if showRun}<th>Run</th>{/if}
        <th>Date</th>
        <th>Seed</th>
        <th title="Main weapon used">Route</th>
        <th>Deaths</th>
      </tr>
    </thead>
    <tbody>
      {#each visible as run (`${run.race_id ?? run.session_id}:${run.user.id}`)}
        {@const seedHref = speedrunSeedHref(run)}
        {@const route = run.weapon
          ? formatCombo(run.weapon, getWeaponName)
          : "–"}
        <!-- A mouse fallback for the player cell's padding, badge and bubble. -->
        <tr
          class:obsolete={run.rank === null}
          onclick={(e) => openSeed(e, seedHref)}
        >
          <td class="rank">
            <a class="cell" href={seedHref} tabindex="-1">
              {#if run.rank !== null && run.rank <= 3}
                <span class="trophy"><SpeedrunTrophy place={run.rank} /></span>
              {:else if run.rank !== null}
                {run.rank}
              {/if}
            </a>
          </td>
          <td class="left player">
            <SpeedrunPlayer
              user={run.user}
              raceName={run.race_name ?? undefined}
              rowHref={seedHref}
            />
          </td>
          <td>
            <a class="cell" href={seedHref} tabindex="-1"
              ><SpeedrunTime ms={run.igt_ms} /></a
            >
          </td>
          {#if showRun}
            <td>
              <a class="cell" href={seedHref} tabindex="-1"
                ><span
                  class="chip run-chip"
                  class:blind={run.blind}
                  class:replay={!run.blind}
                  title={run.blind
                    ? RUN_KIND_TITLES.blind
                    : RUN_KIND_TITLES.replay}
                  >{run.blind ? "Blind" : "Replay"}</span
                ></a
              >
            </td>
          {/if}
          <td title={new Date(run.finished_at).toLocaleString()}>
            <a class="cell" href={seedHref} tabindex="-1"
              >{speedrunAgo(run.finished_at, now)}</a
            >
          </td>
          <td>
            <a
              class="cell seed"
              class:gone={!run.replayable}
              href={seedHref}
              title={run.replayable ? undefined : "No longer replayable"}
              >{run.seed_number.slice(0, 6)}</a
            >
          </td>
          <td class="route-cell" title={run.weapon ? route : undefined}>
            <a class="cell" href={seedHref} tabindex="-1">{route}</a>
          </td>
          <td>
            <a class="cell" href={seedHref} tabindex="-1">{run.deaths}</a>
          </td>
        </tr>
      {/each}
    </tbody>
  </table>
</div>
{#if shown < runs.length}
  <button type="button" class="show-more" onclick={() => (shown += PAGE_SIZE)}>
    Show more ({runs.length - shown} left)
  </button>
{/if}

<style>
  .run-chip {
    padding: 0.1rem 0.4rem;
    font-size: 0.62rem;
  }

  .run-chip.blind {
    color: var(--color-success);
    border-color: color-mix(in srgb, var(--color-success) 60%, transparent);
  }

  .run-chip.replay {
    color: var(--color-purple);
    border-color: color-mix(in srgb, var(--color-purple) 60%, transparent);
  }

  .table-wrap {
    overflow-x: auto;
  }

  .sr-table {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--font-size-sm);
  }

  /* speedrun.com headers: plain bold labels, not the site's mono caps. */
  th {
    padding: 0.55rem 0.45rem;
    background: var(--color-surface-elevated);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-xs);
    font-weight: 700;
    letter-spacing: normal;
    text-transform: none;
    text-align: center;
    white-space: nowrap;
  }

  /* A cell's padding sits on its run link, so the whole cell is the link. */
  td {
    padding: 0;
    border-top: 1px solid var(--color-border);
    text-align: center;
    white-space: nowrap;
  }

  .cell,
  .player {
    padding: 0.42rem 0.45rem;
  }

  .cell {
    display: block;
    color: inherit;
  }

  .cell:hover {
    color: inherit;
  }

  .left {
    text-align: left;
  }

  tbody tr {
    cursor: pointer;
  }

  tbody tr:nth-child(even) td {
    background: color-mix(
      in srgb,
      var(--color-surface-elevated) 35%,
      transparent
    );
  }

  tbody tr:hover td {
    background: color-mix(in srgb, var(--color-purple) 8%, transparent);
  }

  .rank {
    width: 2rem;
    font-weight: 700;
    color: var(--color-text-secondary);
  }

  .trophy {
    display: inline-flex;
    justify-content: center;
  }

  .player {
    max-width: 12rem;
  }

  .obsolete td {
    color: var(--color-text-disabled);
  }

  .obsolete .player {
    opacity: 0.6;
  }

  .seed {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-purple);
    text-decoration: none;
  }

  .seed:hover {
    color: var(--color-purple-hover);
  }

  .seed.gone {
    color: var(--color-text-disabled);
    text-decoration: line-through;
  }

  .seed.gone:hover {
    color: var(--color-text-secondary);
  }

  /* Not .route: app.css owns that global class (the cards' route strip,
     which turns pointer events off and would kill this cell's tooltip). */
  .route-cell {
    max-width: 10rem;
  }

  .route-cell .cell {
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .show-more {
    display: block;
    width: 100%;
    padding: 0.55rem;
    background: var(--color-bg);
    border: none;
    border-top: 1px solid var(--color-border);
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 600;
    cursor: pointer;
  }

  .show-more:hover {
    color: var(--color-purple);
  }
</style>
