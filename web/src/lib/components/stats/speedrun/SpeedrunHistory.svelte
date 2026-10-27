<script lang="ts">
  import type { SpeedrunCategory, SpeedrunRun } from "$lib/api";
  import {
    historyPolyline,
    historyTimeline,
    speedrunDay,
    speedrunDaysLater,
    speedrunRaceHref,
    type SpeedrunView,
  } from "$lib/speedrun";
  import { formatIgt } from "$lib/utils/training";
  import SpeedrunPlayer from "./SpeedrunPlayer.svelte";
  import SpeedrunTime from "./SpeedrunTime.svelte";

  let {
    records,
    category,
    view,
    onview,
  }: {
    /** Successive records, oldest first. */
    records: SpeedrunRun[];
    category: SpeedrunCategory;
    view: Exclude<SpeedrunView, "board">;
    onview: (view: Exclude<SpeedrunView, "board">) => void;
  } = $props();

  const HEIGHT = 180;
  const PAD_X = 16;
  const PAD_Y = 18;

  let width = $state(0);
  // The current record's line runs until the moment the view was opened.
  const nowMs = Date.now();

  let points = $derived(historyPolyline(records, nowMs));
  let tMin = $derived(points.length > 0 ? points[0][0] : nowMs);
  let slowest = $derived(Math.max(...records.map((r) => r.igt_ms)));
  let fastest = $derived(Math.min(...records.map((r) => r.igt_ms)));
  let timeline = $derived(historyTimeline(records));

  function x(t: number): number {
    const span = nowMs - tMin;
    return span > 0 ? PAD_X + ((t - tMin) / span) * (width - 2 * PAD_X) : PAD_X;
  }

  // Faster is lower, as on speedrun.com's record chart.
  function y(igt: number): number {
    const span = slowest - fastest;
    return span > 0
      ? PAD_Y + ((slowest - igt) / span) * (HEIGHT - 2 * PAD_Y)
      : HEIGHT / 2;
  }

  let path = $derived(
    points
      .map(([t, igt], i) => `${i === 0 ? "M" : "L"}${x(t)},${y(igt)}`)
      .join(" "),
  );
</script>

<div class="history">
  <div class="modes">
    <div class="segmented">
      <button
        type="button"
        class:on={view === "history-chart"}
        onclick={() => onview("history-chart")}
      >
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d="M4 4v16h16M8 15l4-5 3 3 4-6"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          />
        </svg>
        Chart
      </button>
      <button
        type="button"
        class:on={view === "history-list"}
        onclick={() => onview("history-list")}
      >
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          />
        </svg>
        List
      </button>
    </div>
  </div>

  {#if records.length === 0}
    <p class="message">No record yet for these filters.</p>
  {:else if view === "history-chart"}
    <!-- Bound on an unpadded box so the SVG matches the space it gets. -->
    <div class="chart">
      <div bind:clientWidth={width}>
        {#if width > 0}
          <svg
            {width}
            height={HEIGHT}
            viewBox="0 0 {width} {HEIGHT}"
            role="img"
            aria-label="Record over time"
          >
            <path d={path} class="line" />
            {#each records as record (`${record.race_id}:${record.user.id}`)}
              <circle
                class="dot"
                cx={x(new Date(record.finished_at).getTime())}
                cy={y(record.igt_ms)}
                r="3.5"
              />
            {/each}
            <text x={PAD_X} y={12} class="axis">{formatIgt(slowest)}</text>
            {#if fastest !== slowest}
              <text x={PAD_X} y={HEIGHT - 4} class="axis"
                >{formatIgt(fastest)}</text
              >
            {/if}
            <text x={width - PAD_X} y={HEIGHT - 4} class="axis end">Today</text>
          </svg>
        {/if}
      </div>
    </div>
  {:else}
    <ol class="timeline">
      {#if category.released_at}
        <li class="entry">
          <span class="dot" aria-hidden="true"></span>
          <p class="headline">{category.name} was released</p>
          <p class="when">{speedrunDay(category.released_at)}</p>
        </li>
      {/if}
      {#each timeline as entry (`${entry.run.race_id}:${entry.run.user.id}`)}
        <li class="entry" class:improved={entry.kind === "improved"}>
          <span class="dot" aria-hidden="true"></span>
          <p class="headline">
            <SpeedrunPlayer user={entry.run.user} inline />
            {entry.kind === "new"
              ? "set a new record time of"
              : "improved their time to"}
            <a class="time" href={speedrunRaceHref(entry.run)}
              ><SpeedrunTime ms={entry.run.igt_ms} /></a
            > !
          </p>
          <p class="when">
            {speedrunDay(entry.run.finished_at)}{entry.daysLater !== null
              ? ` (${speedrunDaysLater(entry.daysLater)})`
              : ""}
          </p>
          {#if entry.improvedBy !== null}
            <p class="gain">
              Record time improved by <SpeedrunTime
                ms={entry.improvedBy}
                gain
              /> .
            </p>
          {/if}
        </li>
      {/each}
    </ol>
  {/if}
</div>

<style>
  .modes {
    padding: 0.55rem 0.55rem 0;
  }

  .segmented {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }

  .segmented button {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.22rem 0.55rem;
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-xs);
    font-weight: 600;
    cursor: pointer;
  }

  .segmented button:hover {
    color: var(--color-purple);
  }

  .segmented button.on {
    background: var(--color-surface-elevated);
    color: var(--color-text);
  }

  .chart {
    padding: 0.6rem 0.55rem 0.2rem;
  }

  svg {
    display: block;
  }

  .line {
    fill: none;
    stroke: var(--color-gold);
    stroke-width: 2;
  }

  circle.dot {
    fill: var(--color-gold);
    stroke: var(--color-surface);
    stroke-width: 1.5;
  }

  .axis {
    fill: var(--color-text-secondary);
    font-family: var(--font-mono);
    font-size: 10px;
  }

  .axis.end {
    text-anchor: end;
  }

  /* speedrun.com's history list: a vertical rail, a big dot per new
     record holder, a small indented one when a holder beats their own. */
  .timeline {
    position: relative;
    margin: 0;
    padding: 0.8rem 0.9rem 0.6rem 2.4rem;
    list-style: none;
  }

  .timeline::before {
    content: "";
    position: absolute;
    top: 1.2rem;
    bottom: 1.2rem;
    left: 1.05rem;
    width: 2px;
    background: color-mix(in srgb, var(--color-text-disabled) 45%, transparent);
  }

  .entry {
    position: relative;
    padding-bottom: 1.1rem;
    overflow-wrap: anywhere;
  }

  span.dot {
    position: absolute;
    top: 0.2rem;
    left: -1.65rem;
    width: 12px;
    height: 12px;
    border-radius: 50%;
    background: var(--color-gold);
    box-shadow: 0 0 0 3px var(--color-surface-elevated);
  }

  .entry.improved {
    padding-left: 0.75rem;
  }

  .entry.improved span.dot {
    top: 0.35rem;
    left: -1.5rem;
    width: 7px;
    height: 7px;
    box-shadow: none;
  }

  .headline {
    margin: 0;
    font-size: var(--font-size-sm);
    font-weight: 700;
  }

  .time {
    color: var(--color-gold);
    text-decoration: none;
  }

  .time:hover {
    color: var(--color-gold-hover);
  }

  .when {
    margin: 0.2rem 0 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
  }

  .gain {
    margin: 0.55rem 0 0;
    font-size: var(--font-size-xs);
  }

  .message {
    margin: 0;
    padding: 1.2rem 0.9rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
</style>
