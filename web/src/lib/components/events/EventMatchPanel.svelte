<script lang="ts">
  import type { Caster, EventStage, EventStageRace } from "$lib/api";
  import {
    cutLine,
    fillSlots,
    formatMatchTime,
    liveMatchMeta,
    matchCasters,
    matchRows,
    type LiveMatch,
  } from "$lib/events";
  import LiveBadge from "$lib/components/LiveBadge.svelte";
  import UserLink from "$lib/components/UserLink.svelte";

  let {
    match,
    stages,
    languages = {},
    now,
    wide = false,
  }: {
    match: LiveMatch;
    /** Every stage of the event: seat codes and the cut line read them. */
    stages: EventStage[];
    /** Caster user id -> language code (`caster_languages`). */
    languages?: Record<string, string>;
    /** The page's clock: a race on another day reads with its day. */
    now: Date;
    /** Alone in the zone: the table beside a column of casters. */
    wide?: boolean;
  } = $props();

  const SIGNALS = {
    live: { cls: "signal-running", text: "Live now" },
    between: { cls: "signal-active", text: "In progress" },
    finished: { cls: "signal-finished", text: "Finished" },
  } as const;

  let stage = $derived(match.stage);
  let slots = $derived(fillSlots(stage.races, stage.races_expected));
  let rows = $derived(matchRows(stage, stages));
  let cut = $derived(cutLine(stage, stages, rows.length));
  let casters = $derived(matchCasters(stage));
  let meta = $derived(liveMatchMeta(match, (iso) => formatMatchTime(iso, now)));
  // The running race's page while it runs, the next race's between two.
  let action = $derived(
    match.race && match.state !== "finished"
      ? {
          href: `/race/${match.race.race.id}`,
          text: match.state === "live" ? "Race page" : "Next race",
        }
      : null,
  );

  const modeOf = (i: number) => stage.modes[i] ?? `Race ${i + 1}`;
  function columnNote(entry: EventStageRace | null): string {
    if (!entry) return "";
    if (entry.race.status === "finished") return "done";
    if (entry.race.status === "running") return "● live";
    return entry.race.scheduled_at
      ? formatMatchTime(entry.race.scheduled_at, now)
      : "";
  }
  // Each caster's own live stream, else their channel.
  const watchUrl = (caster: Caster) =>
    caster.stream_url ?? `https://twitch.tv/${caster.user.twitch_username}`;
</script>

<!-- The casters' column only exists with casters: a lone match nobody casts
     keeps the full width for its table. -->
<article class="match" class:wide={wide && casters.length > 0}>
  <div
    class="route {match.state === 'finished'
      ? 'route-finished'
      : 'route-running'}"
    aria-hidden="true"
  >
    <span class="line"></span><span class="m-start"></span><span class="m-end"
    ></span>
    {#if match.state === "live"}<span class="m-train"></span>{/if}
  </div>
  <div class="head">
    <div>
      <div class="eyebrow">
        <span class="signal {SIGNALS[match.state].cls}"
          >{SIGNALS[match.state].text}</span
        >
        {#if meta}<span class="meta">{meta}</span>{/if}
      </div>
      <h3 class="title">{stage.label}</h3>
    </div>
    {#if action}<a class="btn btn-outline btn-sm" href={action.href}
        >{action.text}</a
      >{/if}
  </div>
  {#if casters.length > 0}
    <ul class="casters">
      {#each casters as caster (caster.user.id)}
        <li class="caster">
          {#if caster.user.twitch_avatar_url}
            <img src={caster.user.twitch_avatar_url} alt="" class="avatar" />
          {:else}
            <span class="avatar avatar-placeholder" aria-hidden="true"></span>
          {/if}
          <div class="who">
            <span class="k">Caster</span>
            <span class="name">
              <UserLink user={caster.user} />
              {#if languages[caster.user.id]}<span class="lang"
                  >{languages[caster.user.id]}</span
                >{/if}
              {#if caster.is_live}<LiveBadge
                  href={watchUrl(caster)}
                  small
                />{/if}
            </span>
          </div>
          <a
            class="btn btn-twitch btn-sm watch"
            href={watchUrl(caster)}
            target="_blank"
            rel="noopener noreferrer"
            ><svg viewBox="0 0 24 24" aria-hidden="true"
              ><path
                d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"
              /></svg
            >{wide ? "Watch on Twitch" : "Watch"}</a
          >
        </li>
      {/each}
    </ul>
  {/if}
  <table class="score">
    <thead>
      <tr>
        <th></th>
        <th class="runner">Runner</th>
        {#each slots as entry, i (i)}
          <th
            class:done={entry?.race.status === "finished"}
            class:live={entry?.race.status === "running"}
          >
            {#if entry}<a href="/race/{entry.race.id}">{modeOf(i)}</a
              >{:else}{modeOf(i)}{/if}
            <span class="note">{columnNote(entry)}</span>
          </th>
        {/each}
        <th>Total</th>
      </tr>
    </thead>
    <tbody>
      {#each rows as row, i (row.user.id)}
        <tr class:out={row.forfeit}>
          <td class="rank" class:gold={row.rank === 1}>{row.rank ?? ""}</td>
          <td class="runner">
            <span class="runner-cell">
              <UserLink user={row.user} showAvatar />
              {#if row.seat}<span class="seat">{row.seat}</span>{/if}
              {#if row.forfeit}<span class="tag">forfeit</span>{/if}
            </span>
          </td>
          {#each row.cells as cell, j (j)}
            <td class="cell {cell.tone}">{cell.text}</td>
          {/each}
          <td
            class="total"
            class:prov={!stage.complete}
            class:adv={row.advances}
          >
            {row.total === null
              ? "·"
              : row.advances
                ? `adv ${row.total}`
                : row.total}
          </td>
        </tr>
        {#if cut && cut.after === i}
          <tr class="cut">
            <td colspan={slots.length + 3}><span>{cut.label}</span></td>
          </tr>
        {/if}
      {/each}
    </tbody>
  </table>
</article>

<style>
  .match {
    position: relative;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    padding: 0.9rem 1rem 0.8rem;
    min-width: 0;
  }
  .match > .route {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 0.75rem;
  }
  .eyebrow {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.3rem 0.75rem;
  }
  .meta {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }
  .title {
    margin: 0.2rem 0 0;
    font-family: var(--font-display);
    font-size: 1.75rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    line-height: 1.1;
  }
  .btn-sm {
    padding: 0.28rem 0.7rem 0.34rem;
    font-size: 0.85rem;
    white-space: nowrap;
  }
  .casters {
    list-style: none;
    margin: 0.8rem 0 0;
    padding: 0;
    display: flex;
    flex-direction: column;
    gap: 6px;
  }
  .caster {
    display: grid;
    grid-template-columns: 32px minmax(0, 1fr) auto;
    align-items: center;
    gap: 0.6rem;
    padding: 0.45rem 0.5rem 0.45rem 0.6rem;
    background: var(--color-surface-elevated);
    border-left: 3px solid var(--color-twitch-hover);
    border-radius: var(--radius-sm);
  }
  .avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    object-fit: cover;
  }
  .avatar-placeholder {
    display: block;
    background: var(--color-border);
  }
  .who {
    min-width: 0;
  }
  .k {
    display: block;
    font-family: var(--font-mono);
    font-size: 0.6rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }
  .name {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    min-width: 0;
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
  .watch {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
  }
  .watch svg {
    width: 13px;
    height: 13px;
    fill: currentColor;
  }
  .score {
    width: 100%;
    border-collapse: collapse;
    margin-top: 0.8rem;
  }
  .score th {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    text-align: right;
    vertical-align: bottom;
    padding: 0 0.4rem 0.4rem;
    line-height: 1.3;
  }
  .score th.runner {
    text-align: left;
  }
  .score th a {
    color: inherit;
    border-bottom: 1px dotted var(--color-text-disabled);
    transition: color var(--transition);
  }
  .score th a:hover {
    color: var(--color-purple-hover);
    border-bottom-color: var(--color-purple-hover);
  }
  .score th.done a {
    color: var(--color-info);
  }
  .score th.live a,
  .score th.live .note {
    color: var(--color-danger);
  }
  .note {
    display: block;
    color: var(--color-text-disabled);
    letter-spacing: 0.04em;
  }
  .score td {
    padding: 0.4rem;
    border-top: 1px solid var(--color-border);
    text-align: right;
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    white-space: nowrap;
  }
  .score td.rank {
    width: 1.6rem;
    padding-left: 0;
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--color-text-secondary);
  }
  .score td.rank.gold {
    color: var(--color-gold);
  }
  .score td.runner {
    text-align: left;
    font-family: var(--font-family);
    font-size: 0.9rem;
    white-space: normal;
  }
  .runner-cell {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
  }
  .seat {
    font-family: var(--font-mono);
    font-size: 0.62rem;
    color: var(--color-text-disabled);
  }
  .tag {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0 4px;
  }
  /* Withdrew after the lock: the name recedes, its tag says why. */
  tr.out .runner-cell > :global(:first-child) {
    opacity: 0.55;
  }
  .cell.prov {
    color: var(--color-gold);
  }
  .cell.live {
    color: var(--color-danger);
  }
  .cell.out,
  .cell.todo {
    color: var(--color-text-disabled);
  }
  .score td.total {
    font-weight: 600;
  }
  .score td.total.prov {
    color: var(--color-gold);
  }
  .score td.total.adv {
    color: var(--color-success);
    font-size: 0.7rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
  }
  tr.cut td {
    position: relative;
    height: 0;
    padding: 0;
    border-top: 1px dashed var(--color-gold);
  }
  tr.cut span {
    position: absolute;
    right: 0.4rem;
    top: -0.5rem;
    padding: 0 0.4rem;
    background: var(--color-surface);
    font-family: var(--font-mono);
    font-size: 0.58rem;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--color-gold);
  }
  /* Alone in the zone: the table on the left, the casters in a column on
   * the right with bigger avatars and full-width buttons. */
  .match.wide {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 300px;
    column-gap: 28px;
    align-items: start;
  }
  .match.wide .head {
    grid-column: 1 / -1;
  }
  .match.wide .casters {
    grid-column: 2;
    grid-row: 2;
  }
  .match.wide .score {
    grid-column: 1;
    grid-row: 2;
  }
  .match.wide .caster {
    grid-template-columns: 40px minmax(0, 1fr);
  }
  .match.wide .avatar {
    width: 40px;
    height: 40px;
  }
  .match.wide .watch {
    grid-column: 1 / -1;
    justify-content: center;
  }
  @media (max-width: 899px) {
    .match.wide {
      display: block;
    }
  }
</style>
