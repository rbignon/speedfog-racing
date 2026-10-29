<script lang="ts">
  import type { SpeedrunRun } from "$lib/api";
  import {
    historyPolyline,
    speedrunDay,
    speedrunTimeParts,
  } from "$lib/speedrun";
  import { dateTicks, nearestPoint, timeTicks } from "$lib/speedrun-chart";
  import SpeedrunPlayer from "./SpeedrunPlayer.svelte";
  import SpeedrunTime from "./SpeedrunTime.svelte";

  /** Successive records, oldest first (at least one). */
  let { records }: { records: SpeedrunRun[] } = $props();

  // The SVG height includes the x-axis band, so no label ever overflows it.
  const HEIGHT = 240;
  const MARGIN = { top: 12, right: 18, bottom: 30, left: 76 };
  const DAY_MS = 86_400_000;
  const BOTTOM = HEIGHT - MARGIN.bottom;
  // Room per date label (a "Jan 2027" label is about 50px wide).
  const DATE_TICK_SPACING = 64;
  const TIP_GAP = 12;

  let width = $state(0);
  let active = $state<number | null>(null);
  let svgEl = $state<SVGSVGElement | null>(null);
  let tipWidth = $state(0);
  let tipHeight = $state(0);
  // The current record holds until the moment the view was opened.
  const nowMs = Date.now();

  let times = $derived(records.map((r) => new Date(r.finished_at).getTime()));
  let points = $derived(historyPolyline(records, nowMs));
  let yAxis = $derived(
    timeTicks(
      Math.min(...records.map((r) => r.igt_ms)),
      Math.max(...records.map((r) => r.igt_ms)),
    ),
  );
  // The axis ends now; a category whose first record is under a day old
  // still gets a day of axis, reaching back before that record.
  let start = $derived(Math.min(times[0], nowMs - DAY_MS));
  let span = $derived(nowMs - start);
  let right = $derived(width - MARGIN.right);
  // As many date labels as the width allows, eight at most.
  let xTicks = $derived(
    dateTicks(
      start,
      nowMs,
      Math.min(
        8,
        Math.max(2, Math.floor((right - MARGIN.left) / DATE_TICK_SPACING)),
      ),
    ),
  );

  function sx(t: number): number {
    return MARGIN.left + ((t - start) / span) * (right - MARGIN.left);
  }

  // Faster is lower, as on speedrun.com's record chart.
  function sy(igt: number): number {
    return (
      MARGIN.top +
      ((yAxis.max - igt) / (yAxis.max - yAxis.min)) * (BOTTOM - MARGIN.top)
    );
  }

  function label(ms: number): string {
    return speedrunTimeParts(ms)
      .map((p) => `${p.value}${p.unit}`)
      .join(" ");
  }

  let xs = $derived(times.map(sx));
  let linePath = $derived(
    points
      .map(([t, igt], i) => `${i ? "L" : "M"}${sx(t)},${sy(igt)}`)
      .join(" "),
  );
  // Closed under the line itself, from the first record to now.
  let areaPath = $derived(
    `${linePath} L${sx(nowMs)},${BOTTOM} L${sx(times[0])},${BOTTOM} Z`,
  );
  let dots = $derived(
    records.map((r, i): [number, number] => [xs[i], sy(r.igt_ms)]),
  );

  // Guarded: a records change can leave a stale index behind.
  let current = $derived(
    active !== null && active < records.length ? records[active] : null,
  );
  // Right of the point when it fits, left of it otherwise, and kept inside
  // the chart vertically (a record near the top would cover the toggles).
  let tipX = $derived.by(() => {
    if (active === null || current === null) return 0;
    const x = dots[active][0];
    const fitsRight = x + TIP_GAP + tipWidth <= width;
    return Math.max(0, fitsRight ? x + TIP_GAP : x - TIP_GAP - tipWidth);
  });
  let tipY = $derived.by(() => {
    if (active === null || current === null) return 0;
    const y = dots[active][1] - tipHeight / 2;
    return Math.min(Math.max(0, y), HEIGHT - tipHeight);
  });

  function handlePointer(e: PointerEvent) {
    if (!svgEl) return;
    const rect = svgEl.getBoundingClientRect();
    active = nearestPoint(dots, e.clientX - rect.left, e.clientY - rect.top);
  }

  // A touch or pen pointer leaves right after it lifts: keep the tapped
  // record shown until the next tap elsewhere blurs the chart.
  function handleLeave(e: PointerEvent) {
    if (e.pointerType === "mouse") active = null;
  }

  function handleKeydown(e: KeyboardEvent) {
    const last = records.length - 1;
    if (e.key === "ArrowLeft") {
      active = Math.max(0, (active ?? last + 1) - 1);
    } else if (e.key === "ArrowRight") {
      active = Math.min(last, (active ?? -1) + 1);
    } else if (e.key === "Escape" && active !== null) {
      active = null;
    } else {
      return;
    }
    e.preventDefault();
  }
</script>

<!-- Bound on an unpadded box so the SVG matches the space it gets. -->
<div class="chart">
  <div class="frame" bind:clientWidth={width}>
    {#if width > MARGIN.left + MARGIN.right}
      <svg
        bind:this={svgEl}
        {width}
        height={HEIGHT}
        viewBox="0 0 {width} {HEIGHT}"
        role="slider"
        tabindex="0"
        aria-label="Record over time; arrow keys step through the records"
        aria-valuemin={1}
        aria-valuemax={records.length}
        aria-valuenow={(active ?? records.length - 1) + 1}
        aria-valuetext={current
          ? `${current.user.twitch_display_name || current.user.twitch_username}, ${label(current.igt_ms)}, ${speedrunDay(current.finished_at)}`
          : "No record selected"}
        onpointermove={handlePointer}
        onpointerdown={handlePointer}
        onpointerleave={handleLeave}
        onkeydown={handleKeydown}
        onblur={() => (active = null)}
      >
        {#each yAxis.ticks as tick (tick)}
          <line
            class="grid"
            x1={MARGIN.left}
            x2={right}
            y1={sy(tick)}
            y2={sy(tick)}
          />
          <text class="axis y" x={MARGIN.left - 8} y={sy(tick)}
            >{label(tick)}</text
          >
        {/each}
        {#each xTicks as tick (tick.time)}
          <line
            class="tick"
            x1={sx(tick.time)}
            x2={sx(tick.time)}
            y1={BOTTOM}
            y2={BOTTOM + 4}
          />
          <text class="axis x" x={sx(tick.time)} y={BOTTOM + 18}
            >{tick.label}</text
          >
        {/each}
        <line
          class="baseline"
          x1={MARGIN.left}
          x2={right}
          y1={BOTTOM}
          y2={BOTTOM}
        />

        <path class="area" d={areaPath} />
        <path class="line" d={linePath} />
        {#if current !== null && active !== null}
          <line
            class="crosshair"
            x1={dots[active][0]}
            x2={dots[active][0]}
            y1={MARGIN.top}
            y2={BOTTOM}
          />
        {/if}
        {#each records as record, i (`${record.race_id ?? record.session_id}:${record.user.id}`)}
          <circle
            class="dot"
            class:on={i === active}
            cx={dots[i][0]}
            cy={dots[i][1]}
            r={i === active ? 6 : 4}
          />
        {/each}
      </svg>
      {#if current !== null}
        <!-- inert: the player link inside must not take focus away from the
             chart (its blur would close the tooltip). -->
        <div
          class="tooltip"
          inert
          bind:offsetWidth={tipWidth}
          bind:offsetHeight={tipHeight}
          style:left="{tipX}px"
          style:top="{tipY}px"
        >
          <strong><SpeedrunTime ms={current.igt_ms} /></strong>
          <SpeedrunPlayer user={current.user} inline />
          <span class="when">{speedrunDay(current.finished_at)}</span>
        </div>
      {/if}
    {/if}
  </div>
</div>

<style>
  .chart {
    padding: 0.6rem 0.55rem 0.2rem;
  }

  .frame {
    position: relative;
  }

  svg {
    display: block;
    outline: none;
    touch-action: pan-y;
  }

  svg:focus-visible {
    outline: 1px solid var(--color-purple);
    outline-offset: 2px;
  }

  /* Recessive frame: solid hairlines one step off the surface. */
  .grid,
  .baseline,
  .tick {
    stroke: var(--color-border);
    stroke-width: 1;
    shape-rendering: crispEdges;
  }

  .axis {
    fill: var(--color-text-secondary);
    font-family: var(--font-mono);
    font-size: 10.5px;
    font-variant-numeric: tabular-nums;
  }

  .axis.y {
    text-anchor: end;
    dominant-baseline: middle;
  }

  .axis.x {
    text-anchor: middle;
  }

  .area {
    fill: var(--color-gold);
    opacity: 0.1;
  }

  .line {
    fill: none;
    stroke: var(--color-gold);
    stroke-width: 2;
    stroke-linejoin: round;
    stroke-linecap: round;
  }

  .crosshair {
    stroke: var(--color-text-disabled);
    stroke-width: 1;
    shape-rendering: crispEdges;
  }

  /* The surface ring keeps a dot readable where it sits on the line. */
  .dot {
    fill: var(--color-gold);
    stroke: var(--color-surface);
    stroke-width: 2;
  }

  .dot.on {
    fill: var(--color-gold-hover);
  }

  .tooltip {
    position: absolute;
    z-index: 2;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    padding: 0.45rem 0.6rem;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    font-size: var(--font-size-xs);
    white-space: nowrap;
    pointer-events: none;
  }

  .tooltip strong {
    font-size: var(--font-size-sm);
  }

  .when {
    color: var(--color-text-secondary);
  }
</style>
