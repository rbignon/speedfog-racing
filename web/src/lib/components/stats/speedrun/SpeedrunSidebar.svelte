<script lang="ts">
  import { goto } from "$app/navigation";
  import type { Race, SpeedrunOverviewResponse } from "$lib/api";
  import RaceCard from "$lib/components/RaceCard.svelte";
  import { ordinal } from "$lib/events";
  import { seedPageHref, speedrunAgo, speedrunSeedHref } from "$lib/speedrun";
  import { getWeaponName } from "$lib/stores/weaponsCatalogue.svelte";
  import { formatCombo } from "$lib/weapons";
  import SpeedrunPlayer from "./SpeedrunPlayer.svelte";
  import SpeedrunTime from "./SpeedrunTime.svelte";
  import SpeedrunTrophy from "./SpeedrunTrophy.svelte";

  let {
    overview,
    races = [],
  }: {
    overview: SpeedrunOverviewResponse;
    /** Active races (setup or running), split below into live and upcoming. */
    races?: Race[];
  } = $props();

  let liveRaces = $derived(races.filter((r) => r.status === "running"));
  // Like /races: a race in setup shows once it has a date, soonest first.
  let upcomingRaces = $derived(
    races
      .filter((r) => r.status === "setup" && r.scheduled_at)
      .sort(
        (a, b) =>
          new Date(a.scheduled_at!).getTime() -
          new Date(b.scheduled_at!).getTime(),
      ),
  );

  const now = Date.now();

  const plural = (n: number, word: string) =>
    `${n} ${word}${n === 1 ? "" : "s"}`;

  // Every part of a recent PB but the player's name and badge is a link to
  // its run, so the row acts as one link (a modified or middle click opens a
  // new tab); only the category's link is in the tab order. On the rest (the
  // margins, the badge), a plain click opens the run too, unless it ended a
  // text selection; a modified click there does nothing rather than open the
  // run in this tab.
  function openRun(e: MouseEvent, href: string) {
    if ((e.target as Element).closest("a, button")) return;
    if (e.metaKey || e.ctrlKey || e.shiftKey) return;
    if (window.getSelection()?.toString()) return;
    void goto(href);
  }
</script>

<aside class="sr-side">
  {#if liveRaces.length > 0}
    <section class="races">
      <h3>Live races</h3>
      {#each liveRaces as race (race.id)}
        <RaceCard {race} variant="narrow" />
      {/each}
    </section>
  {/if}

  {#if upcomingRaces.length > 0}
    <section class="races">
      <h3>Upcoming races</h3>
      {#each upcomingRaces as race (race.id)}
        <RaceCard {race} variant="narrow" />
      {/each}
    </section>
  {/if}

  <section class="sr-panel">
    <h3>Game stats</h3>
    <div class="game-stats">
      <div>Runs<b>{overview.runs.toLocaleString("en-US")}</b></div>
      <div>Players<b>{overview.players.toLocaleString("en-US")}</b></div>
      <div>Categories<b>{overview.categories.length}</b></div>
    </div>
  </section>

  {#if overview.practiced_seeds.length > 0}
    <section class="sr-panel">
      <h3>
        Most practiced seeds <span class="window"
          >{plural(overview.practiced_seeds_days, "day")}</span
        >
      </h3>
      {#each overview.practiced_seeds as seed (seed.seed_number)}
        <a class="practiced" href={seedPageHref(seed.seed_number)}>
          <span class="seed"
            >{seed.seed_number.slice(0, 6)} ({seed.category_name})</span
          >
          <span class="counts"
            >{plural(seed.attempts, "attempt")}, {plural(
              seed.players,
              "player",
            )}</span
          >
        </a>
      {/each}
    </section>
  {/if}

  <section class="sr-panel">
    <h3>Recent PBs</h3>
    {#each overview.recent_runs as run (`${run.race_id ?? run.session_id}:${run.user.id}`)}
      {@const href = speedrunSeedHref(run)}
      <!-- A mouse fallback for the margins and the badge. -->
      <!-- svelte-ignore a11y_no_static_element_interactions -->
      <!-- svelte-ignore a11y_click_events_have_key_events -->
      <div class="recent" onclick={(e) => openRun(e, href)}>
        <a
          class="category"
          {href}
          aria-label="{run.category}: run by {run.user.twitch_display_name ||
            run.user.twitch_username}">{run.category}</a
        >
        <a class="details" {href} tabindex="-1">
          {run.blind ? "Blind" : "Replay"}{run.deathless ? ", Deathless" : ""} ({run.weapon
            ? formatCombo(run.weapon, getWeaponName)
            : "–"})
        </a>
        <div class="line">
          <a class="place" {href} tabindex="-1">
            {#if run.rank !== null && run.rank <= 3}
              <SpeedrunTrophy place={run.rank} />
            {/if}
            {run.rank !== null ? ordinal(run.rank) : ""}
          </a>
          <SpeedrunPlayer user={run.user} rowHref={href} />
          <a class="time" {href} tabindex="-1"
            ><SpeedrunTime ms={run.igt_ms} /></a
          >
          <a class="ago" {href} tabindex="-1"
            >{speedrunAgo(run.finished_at, now)}</a
          >
        </div>
      </div>
    {:else}
      <p class="empty">No runs yet.</p>
    {/each}
  </section>

  <p class="parody">
    This page deliberately parodies <a
      href="https://www.speedrun.com"
      target="_blank"
      rel="noopener noreferrer">speedrun.com</a
    >. SpeedFog is not affiliated with it.
  </p>
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

  /* Race cards sit on the column itself, not in a panel: their route
   * line is their top edge. */
  .races {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
  }

  .races h3 {
    padding: 0 0.1rem;
    font-size: 0.9rem;
  }

  .window {
    margin-left: 0.3rem;
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-xs);
    font-weight: 400;
    letter-spacing: 0;
    text-transform: none;
  }

  .practiced {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
    padding: 0.55rem 0.8rem;
    border-top: 1px solid var(--color-border);
    font-size: var(--font-size-sm);
    text-decoration: none;
  }

  .practiced .seed {
    color: var(--color-gold);
    font-weight: 700;
  }

  .practiced:hover .seed {
    color: var(--color-gold-hover);
  }

  .practiced .counts {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
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
    cursor: pointer;
  }

  .category {
    display: block;
    color: var(--color-gold);
    font-weight: 700;
    text-decoration: none;
  }

  .recent:hover .category {
    color: var(--color-gold-hover);
  }

  /* Padding, not margin: the space between the lines is part of the link. */
  .details {
    display: block;
    padding: 0.15rem 0 0.35rem;
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
    color: inherit;
    font-weight: 700;
  }

  .time {
    color: inherit;
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

  .parody {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    line-height: 1.5;
  }
</style>
