<script lang="ts">
  import type { EventStage, EventStageRace } from "$lib/api";
  import {
    cutLine,
    fillSlots,
    formatMatchTime,
    liveMatchMeta,
    matchCasters,
    matchRows,
    type LiveMatch,
  } from "$lib/events";
  import UserLink from "$lib/components/UserLink.svelte";
  import EventCasters from "./EventCasters.svelte";

  let {
    match,
    stages,
    languages = {},
    now,
    compact = false,
  }: {
    match: LiveMatch;
    /** The event's stages: the table's seat codes and cut line read them. */
    stages: EventStage[];
    /** Caster user id -> language code (`caster_languages`). */
    languages?: Record<string, string>;
    /** The page's clock: a race on another day reads with its day. */
    now: Date;
    /**
     * The home band's block: the runners in a line with their match total,
     * without the table or the running race's progress.
     */
    compact?: boolean;
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
</script>

<article class="match">
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
  {#if compact}
    <ol class="runners">
      {#each rows as row (row.user.id)}
        <li class:out={row.forfeit}>
          <span class="rank" class:gold={row.rank === 1}>{row.rank ?? ""}</span>
          <UserLink user={row.user} showAvatar />
          {#if row.total !== null}<span
              class="total"
              class:prov={!stage.complete}
              class:adv={row.advances}
              >{row.advances ? `adv ${row.total}` : `${row.total} pts`}</span
            >{/if}
        </li>
      {/each}
    </ol>
  {:else}
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
  {/if}
  {#if casters.length > 0}<EventCasters {casters} {languages} />{/if}
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
  /* The home band's block: one line per runner, wrapping on phones. */
  .runners {
    list-style: none;
    margin: 0.7rem 0 0;
    padding: 0;
    display: flex;
    flex-wrap: wrap;
    gap: 0.45rem 1.5rem;
  }
  .runners li {
    display: inline-flex;
    align-items: center;
    gap: 0.45rem;
    font-size: 0.9rem;
  }
  .runners .rank {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    font-weight: 600;
    color: var(--color-text-secondary);
  }
  .runners .rank:empty {
    display: none;
  }
  .runners .rank.gold {
    color: var(--color-gold);
  }
  .runners .total {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    font-weight: 600;
  }
  .runners .total.prov {
    color: var(--color-gold);
  }
  .runners .total.adv {
    color: var(--color-success);
    font-size: 0.7rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
  }
  .runners li.out {
    opacity: 0.55;
  }
</style>
