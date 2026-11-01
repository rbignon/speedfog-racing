<script lang="ts">
  import type { EventStage } from "$lib/api";
  import {
    fillSlots,
    formatEventDate,
    formatMatchTime,
    formatStageDate,
    matchCasters,
    seatTag,
    startsIn,
    type UpcomingMatch,
  } from "$lib/events";
  import UserLink from "$lib/components/UserLink.svelte";
  import EventCasters from "./EventCasters.svelte";

  /**
   * One match of the bracket's Up next box: its runners, its casters, then
   * its races as small links. A panel, not a card: it holds several links.
   */
  let {
    match,
    stages,
    languages = {},
    now,
  }: {
    match: UpcomingMatch;
    /** Every stage of the event, for the fed seats' codes. */
    stages: EventStage[];
    /** Caster user id -> language code (`caster_languages`). */
    languages?: Record<string, string>;
    now: Date;
  } = $props();

  let stage = $derived(match.stage);
  let runners = $derived(
    stage.field.flatMap((slot) =>
      slot.user ? [{ slot, user: slot.user }] : [],
    ),
  );
  let casters = $derived(matchCasters(stage));
  let slots = $derived(fillSlots(stage.races, stage.races_expected));
  // Ahead of the viewer: the date names their timezone.
  let when = $derived(
    formatStageDate(match.at, match.timeSet, (iso) =>
      formatEventDate(iso, true),
    ),
  );
  let relative = $derived(match.timeSet ? startsIn(match.at, now) : null);
</script>

<div class="next">
  <div class="route route-setup" aria-hidden="true">
    <span class="line"></span><span class="m-start"></span><span class="m-end"
    ></span>
  </div>
  <div class="head">
    <h3 class="title">{stage.label}</h3>
    <span class="when"
      >{when}{#if relative}<small>{relative}</small>{/if}</span
    >
  </div>
  <ul class="runners">
    {#each runners as { slot, user } (user.id)}
      <li class:out={slot.forfeited}>
        <span class="seat">{seatTag(slot, stages) ?? ""}</span>
        <UserLink {user} showAvatar showBadge />
      </li>
    {/each}
  </ul>
  <EventCasters {casters} {languages} stacked />
  <div class="chips">
    {#each slots as entry, i (i)}
      {@const label = stage.modes[i] ?? `Race ${i + 1}`}
      {#if entry}
        <a class="chip" href="/race/{entry.race.id}"
          >{label}{#if entry.race.scheduled_at}<b
              >{formatMatchTime(entry.race.scheduled_at, new Date(match.at))}</b
            >{/if}</a
        >
      {:else}
        <span class="chip">{label}</span>
      {/if}
    {/each}
  </div>
</div>

<style>
  .next {
    position: relative;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    padding: 0.75rem 0.95rem 0.8rem;
    min-width: 0;
  }
  .next > .route {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.6rem;
  }
  .title {
    margin: 0;
    font-family: var(--font-display);
    font-size: 1.3rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
  }
  .when {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--color-gold);
    text-align: right;
  }
  .when small {
    display: block;
    font-size: 0.66rem;
    color: var(--color-text-secondary);
  }
  .runners {
    list-style: none;
    margin: 0.5rem 0 0;
    padding: 0;
  }
  .runners li {
    display: grid;
    grid-template-columns: 2.2rem minmax(0, 1fr);
    gap: 0.5rem;
    align-items: center;
    padding: 0.25rem 0;
    border-top: 1px solid var(--color-border);
  }
  .runners li:first-child {
    border-top: 0;
  }
  .seat {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--color-text-secondary);
    text-align: right;
  }
  /* Withdrew after the lock: the name recedes. */
  .runners li.out > :global(:last-child) {
    opacity: 0.55;
  }
  .chips {
    display: flex;
    flex-wrap: wrap;
    gap: 4px;
    margin-top: 0.65rem;
  }
  .chips .chip {
    font-size: 0.6rem;
    padding: 0.1rem 0.4rem;
    text-decoration: none;
    transition:
      color var(--transition),
      border-color var(--transition);
  }
  /* A chip that leads to its race page hovers like the site's links */
  .chips a.chip:hover {
    color: var(--color-purple-hover);
    border-color: var(--color-purple-hover);
  }
  .chips .chip b {
    margin-left: 0.3rem;
    font-weight: 500;
    color: var(--color-text);
  }
</style>
