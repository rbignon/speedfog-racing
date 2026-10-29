<script lang="ts">
  import type { SpeedrunRun } from "$lib/api";
  import { speedrunAgo, speedrunSeedHref } from "$lib/speedrun";
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
  let visible = $derived(runs.slice(0, shown));
</script>

<div class="table-wrap">
  <table class="sr-table">
    <thead>
      <tr>
        <th>#</th>
        <th class="left">Player</th>
        <th>Time</th>
        {#if showRun}<th>Run</th>{/if}
        <th>Date</th>
        <th>Seed</th>
        <th>Route</th>
        <th>Deaths</th>
      </tr>
    </thead>
    <tbody>
      {#each visible as run (`${run.race_id ?? run.session_id}:${run.user.id}`)}
        {@const seedHref = speedrunSeedHref(run)}
        {@const route = run.weapon
          ? formatCombo(run.weapon, getWeaponName)
          : "–"}
        <tr class:obsolete={run.rank === null}>
          <td class="rank">
            {#if run.rank !== null && run.rank <= 3}
              <span class="trophy"><SpeedrunTrophy place={run.rank} /></span>
            {:else if run.rank !== null}
              {run.rank}
            {/if}
          </td>
          <td class="left player">
            <SpeedrunPlayer
              user={run.user}
              raceName={run.race_name ?? undefined}
            />
          </td>
          <td><SpeedrunTime ms={run.igt_ms} /></td>
          {#if showRun}
            <td
              ><span
                class="chip run-chip"
                class:blind={run.blind}
                class:replay={!run.blind}>{run.blind ? "Blind" : "Replay"}</span
              ></td
            >
          {/if}
          <td title={new Date(run.finished_at).toLocaleString()}
            >{speedrunAgo(run.finished_at, now)}</td
          >
          <td>
            {#if seedHref}
              <a class="seed" href={seedHref}>{run.seed_number.slice(0, 6)}</a>
            {:else}
              {run.seed_number.slice(0, 6)}
            {/if}
          </td>
          <td class="route-cell" title={run.weapon ? route : undefined}
            >{route}</td
          >
          <td>{run.deaths}</td>
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

  td {
    padding: 0.42rem 0.45rem;
    border-top: 1px solid var(--color-border);
    text-align: center;
    white-space: nowrap;
  }

  .left {
    text-align: left;
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

  /* Not .route: app.css owns that global class (the cards' route strip,
     which turns pointer events off and would kill this cell's tooltip). */
  .route-cell {
    max-width: 10rem;
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
