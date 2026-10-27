<script lang="ts">
  import type { SpeedrunRun } from "$lib/api";
  import { historyPolyline, speedrunRaceHref } from "$lib/speedrun";
  import { formatIgt } from "$lib/utils/training";
  import SpeedrunPlayer from "./SpeedrunPlayer.svelte";
  import SpeedrunTime from "./SpeedrunTime.svelte";

  /** Successive records, oldest first. */
  let { records }: { records: SpeedrunRun[] } = $props();

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
  let newestFirst = $derived([...records].reverse());

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

{#if records.length === 0}
  <p class="message">No record yet for these filters.</p>
{:else}
  <div class="history">
    <div class="chart">
      <!-- Bound on an unpadded box so the SVG matches the space it gets. -->
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

    <div class="table-wrap">
      <table class="records">
        <thead>
          <tr>
            <th class="left">Date</th>
            <th class="left">Player</th>
            <th>Time</th>
            <th>Seed</th>
          </tr>
        </thead>
        <tbody>
          {#each newestFirst as record (`${record.race_id}:${record.user.id}`)}
            <tr>
              <td class="left date"
                >{new Date(record.finished_at).toLocaleDateString("en-US", {
                  month: "short",
                  day: "numeric",
                  year: "numeric",
                })}</td
              >
              <td class="left"><SpeedrunPlayer user={record.user} /></td>
              <td><SpeedrunTime ms={record.igt_ms} /></td>
              <td>
                <a class="seed" href={speedrunRaceHref(record)}
                  >{record.seed_number.slice(0, 6)}</a
                >
              </td>
            </tr>
          {/each}
        </tbody>
      </table>
    </div>
  </div>
{/if}

<style>
  .chart {
    padding: 0.6rem 0.55rem 0.2rem;
    border-bottom: 1px solid var(--color-border);
  }

  svg {
    display: block;
  }

  .line {
    fill: none;
    stroke: var(--color-gold);
    stroke-width: 2;
  }

  .dot {
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

  .table-wrap {
    overflow-x: auto;
  }

  .records {
    width: 100%;
    border-collapse: collapse;
    font-size: var(--font-size-sm);
  }

  /* Same plain headers as the ranking table. */
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

  .date {
    color: var(--color-text-secondary);
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

  .message {
    margin: 0;
    padding: 1.2rem 0.9rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
</style>
