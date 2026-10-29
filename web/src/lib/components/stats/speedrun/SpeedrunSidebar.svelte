<script lang="ts">
  import type { SpeedrunOverviewResponse } from "$lib/api";
  import { ordinal } from "$lib/events";
  import { speedrunAgo } from "$lib/speedrun";
  import { getWeaponName } from "$lib/stores/weaponsCatalogue.svelte";
  import { formatCombo } from "$lib/weapons";
  import SpeedrunPlayer from "./SpeedrunPlayer.svelte";
  import SpeedrunTime from "./SpeedrunTime.svelte";
  import SpeedrunTrophy from "./SpeedrunTrophy.svelte";

  let {
    overview,
    onpick,
  }: {
    overview: SpeedrunOverviewResponse;
    onpick: (pool: string) => void;
  } = $props();

  const now = Date.now();
</script>

<aside class="sr-side">
  <section class="sr-panel">
    <h3>Game stats</h3>
    <div class="game-stats">
      <div>Runs<b>{overview.runs.toLocaleString("en-US")}</b></div>
      <div>Players<b>{overview.players.toLocaleString("en-US")}</b></div>
      <div>Categories<b>{overview.categories.length}</b></div>
    </div>
  </section>

  <section class="sr-panel">
    <h3>Recent runs</h3>
    {#each overview.recent_runs as run (`${run.race_id ?? run.session_id}:${run.user.id}`)}
      <div class="recent">
        <button type="button" class="category" onclick={() => onpick(run.pool)}
          >{run.category}</button
        >
        <div class="details">
          {run.blind ? "Blind" : "Replay"}{run.deathless ? " · Deathless" : ""} ({run.weapon
            ? formatCombo(run.weapon, getWeaponName)
            : "–"})
        </div>
        <div class="line">
          <span class="place">
            {#if run.rank !== null && run.rank <= 3}
              <SpeedrunTrophy place={run.rank} />
            {/if}
            {run.rank !== null ? ordinal(run.rank) : ""}
          </span>
          <SpeedrunPlayer user={run.user} />
          <SpeedrunTime ms={run.igt_ms} />
          <span class="ago">{speedrunAgo(run.finished_at, now)}</span>
        </div>
      </div>
    {:else}
      <p class="empty">No runs yet.</p>
    {/each}
  </section>
</aside>

<style>
  .sr-side {
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-width: 0;
  }

  h3 {
    margin: 0;
    padding: 0.7rem 0.8rem 0.5rem;
    font-family: var(--font-display);
    font-size: 1rem;
    font-weight: 700;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }

  .game-stats {
    display: flex;
    gap: 1.4rem;
    padding: 0 0.8rem 0.8rem;
  }

  .game-stats div {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .game-stats b {
    display: block;
    margin-top: 0.15rem;
    font-size: var(--font-size-base);
    color: var(--color-text);
  }

  .recent {
    padding: 0.55rem 0.8rem;
    border-top: 1px solid var(--color-border);
    font-size: var(--font-size-sm);
  }

  .category {
    padding: 0;
    background: none;
    border: none;
    color: var(--color-gold);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 700;
    cursor: pointer;
  }

  .category:hover {
    color: var(--color-gold-hover);
  }

  .details {
    margin: 0.15rem 0 0.35rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
  }

  .line {
    display: grid;
    grid-template-columns: 4rem minmax(0, 1fr);
    gap: 0.2rem 0.6rem;
    align-items: center;
  }

  .place {
    display: flex;
    align-items: center;
    gap: 0.25rem;
    font-weight: 700;
  }

  .ago {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
  }

  .empty {
    margin: 0;
    padding: 0.55rem 0.8rem 0.8rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
</style>
