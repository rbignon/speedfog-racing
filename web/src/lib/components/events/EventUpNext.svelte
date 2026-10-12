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
  <div class="cast">
    <span class="k"
      ><svg viewBox="0 0 24 24" aria-hidden="true"
        ><path
          d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"
        /></svg
      >Cast by</span
    >
    {#each casters as caster (caster.user.id)}
      <span class="caster"
        ><UserLink
          user={caster.user}
          showAvatar
        />{#if languages[caster.user.id]}<span class="lang"
            >{languages[caster.user.id]}</span
          >{/if}</span
      >
    {:else}
      <span class="tba">Casters to be announced</span>
    {/each}
  </div>
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
  .cast {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem 0.9rem;
    margin-top: 0.6rem;
    padding-top: 0.6rem;
    border-top: 1px solid var(--color-border);
  }
  .cast .k {
    width: 100%;
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    font-family: var(--font-mono);
    font-size: 0.6rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-twitch-hover);
  }
  .cast .k svg {
    width: 12px;
    height: 12px;
    fill: currentColor;
  }
  .caster {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-weight: 600;
  }
  .lang {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0 4px;
    color: var(--color-text-secondary);
  }
  .tba {
    color: var(--color-text-disabled);
    font-style: italic;
    font-size: var(--font-size-sm);
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
