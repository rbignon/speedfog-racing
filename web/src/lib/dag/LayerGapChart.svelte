<script module lang="ts">
  import type { GapSeries } from "$lib/layer-gaps";

  export interface ChartLine {
    id: string;
    color: string;
    name: string;
    series: GapSeries;
  }
</script>

<script lang="ts">
  import { SKULL_PATH } from "$lib/components/SkullIcon.svelte";
  import { formatGap } from "$lib/gap";
  import { chartKey, gapTicks, gateXs, layerAtX } from "$lib/layer-gaps";

  interface Props {
    lines: ChartLine[];
    /** Each layer's column x, in the map's layout units. */
    layerXs: number[];
    /** The map's current view, followed horizontally only: its pan and
     * zoom, and how the map renders layout units (ZoomableSvg's viewScale
     * and viewOriginX), so the chart never copies the map's box. */
    zoom: number;
    panX: number;
    viewScale: number;
    viewOriginX: number;
    activeLayer: number | null;
    pinnedLayer: number | null;
    onhover: (layer: number | null) => void;
    onpin: (layer: number | null) => void;
  }

  let {
    lines,
    layerXs,
    zoom,
    panX,
    viewScale,
    viewOriginX,
    activeLayer,
    pinnedLayer,
    onhover,
    onpin,
  }: Props = $props();

  const HEIGHT = 200;
  // Room above the leading line for a death skull drawn on it.
  const TOP = 18;
  const BOTTOM = 22;
  const PLOT_HEIGHT = HEIGHT - TOP - BOTTOM;
  const SKULL_SIZE = 12;
  const TERMINUS_HALF = 6;

  let svgEl: SVGSVGElement | undefined = $state();
  let frameWidth = $state(0);
  let totalLayers = $derived(layerXs.length);
  let gates = $derived(gateXs(layerXs));

  let maxGap = $derived(
    lines.reduce(
      (max, line) =>
        line.series.points.reduce((m, p) => Math.max(m, p.gapMs), max),
      0,
    ),
  );
  let ticks = $derived(gapTicks(maxGap));
  let tickValues = $derived(
    Array.from(
      { length: Math.round(ticks.topMs / ticks.stepMs) + 1 },
      (_, i) => i * ticks.stepMs,
    ),
  );

  function y(gapMs: number): number {
    return TOP + (gapMs / ticks.topMs) * PLOT_HEIGHT;
  }

  /** A layout x as a pixel x in the chart, where the map draws it. */
  function px(x: number): number {
    return viewOriginX + viewScale * (panX + zoom * x);
  }

  function linePoints(line: ChartLine): string {
    return line.series.points
      .map((p) => `${gates[p.index]},${y(p.gapMs)}`)
      .join(" ");
  }

  function layerAt(event: MouseEvent): number | null {
    if (!svgEl || viewScale === 0) return null;
    const rect = svgEl.getBoundingClientRect();
    const x =
      ((event.clientX - rect.left - viewOriginX) / viewScale - panX) / zoom;
    return layerAtX(x, gates);
  }

  function onClick(event: MouseEvent) {
    const layer = layerAt(event);
    if (layer === null) return;
    onpin(layer === pinnedLayer ? null : layer);
  }

  function onKeydown(event: KeyboardEvent) {
    const action = chartKey(event.key, pinnedLayer, activeLayer, totalLayers);
    if (!action) return;
    // Handled: the leaderboard leaves a prevented Escape alone instead of
    // clearing the selection.
    event.preventDefault();
    onpin(action.pin);
  }
</script>

<div class="gap-chart">
  <div class="chart-title">Gap to the first of the selection, per depth</div>
  <div class="chart-frame" bind:clientWidth={frameWidth}>
    {#if frameWidth > 0 && viewScale > 0 && totalLayers > 0}
      <svg
        bind:this={svgEl}
        width={frameWidth}
        height={HEIGHT}
        viewBox="0 0 {frameWidth} {HEIGHT}"
        role="slider"
        tabindex="0"
        aria-label="Depth comparison"
        aria-valuemin={1}
        aria-valuemax={totalLayers}
        aria-valuenow={(activeLayer ?? 0) + 1}
        aria-valuetext={activeLayer === null
          ? "No depth selected"
          : `Depth ${activeLayer + 1}`}
        onpointermove={(e) => onhover(layerAt(e))}
        onpointerleave={() => onhover(null)}
        onclick={onClick}
        onkeydown={onKeydown}
      >
        {#each tickValues as tick (tick)}
          <line class="grid" x1="0" x2={frameWidth} y1={y(tick)} y2={y(tick)} />
        {/each}

        <!-- Layout x in, chart pixels out: the map's pan and zoom on x only. -->
        <g
          transform="matrix({viewScale * zoom} 0 0 1 {viewOriginX +
            viewScale * panX} 0)"
        >
          {#each gates.slice(0, -1) as gateX, layer (layer)}
            {#if layer % 2 === 0}
              <rect
                class="band"
                x={gateX}
                y={TOP}
                width={gates[layer + 1] - gateX}
                height={PLOT_HEIGHT}
              />
            {/if}
          {/each}
          {#if activeLayer !== null}
            <rect
              class="band-active"
              class:pinned={activeLayer === pinnedLayer}
              x={gates[activeLayer]}
              y={TOP}
              width={gates[activeLayer + 1] - gates[activeLayer]}
              height={PLOT_HEIGHT}
            />
          {/if}
          {#each lines as line (line.id)}
            <polyline
              class="gap-line"
              points={linePoints(line)}
              stroke={line.color}
            >
              <title>{line.name}</title>
            </polyline>
            {#if line.series.terminus && line.series.points.length > 0}
              {@const last = line.series.points[line.series.points.length - 1]}
              <line
                class="terminus"
                x1={gates[last.index]}
                x2={gates[last.index]}
                y1={y(last.gapMs) - TERMINUS_HALF}
                y2={y(last.gapMs) + TERMINUS_HALF}
                stroke={line.color}
              />
            {/if}
          {/each}
        </g>

        {#each lines as line (line.id)}
          {#each line.series.deathMarks as mark (mark.layer)}
            {@const markX = px(layerXs[mark.layer])}
            {@const markY = y(mark.midGapMs)}
            <g
              class="skull"
              transform="translate({markX - SKULL_SIZE / 2} {markY -
                SKULL_SIZE -
                3}) scale({SKULL_SIZE / 24})"
            >
              <path d={SKULL_PATH} fill-rule="evenodd" />
            </g>
            {#if mark.count > 1}
              <text
                class="skull-count"
                x={markX + SKULL_SIZE / 2 + 1}
                y={markY - 4}>{mark.count}</text
              >
            {/if}
          {/each}
        {/each}

        {#each tickValues as tick (tick)}
          <text class="tick" x="4" y={y(tick) + (tick === 0 ? 10 : 4)}
            >{tick === 0 ? "lead" : formatGap(tick)}</text
          >
        {/each}
        <!-- Depths count from 1, like the node popup. The last
               column's number would run into "Finish". -->
        {#each layerXs as layerX, layer (layer)}
          {#if layer === 0 || ((layer + 1) % 5 === 0 && layer < totalLayers - 1)}
            <text
              class="axis"
              x={px(layerX)}
              y={HEIGHT - 6}
              text-anchor="middle">{layer + 1}</text
            >
          {/if}
        {/each}
        <text
          class="axis"
          x={px(gates[totalLayers])}
          y={HEIGHT - 6}
          text-anchor="end">Finish</text
        >
      </svg>
    {/if}
  </div>
</div>

<style>
  .gap-chart {
    margin-top: 0.5rem;
  }

  .chart-title {
    font-family: var(--font-display);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    margin-bottom: 0.25rem;
  }

  /* As wide as the map's container: x positions come from the map's own
     rendering (viewScale, viewOriginX), whatever its min-width or crop. */
  .chart-frame {
    overflow: hidden;
    background: var(--color-surface);
    border-radius: var(--radius-lg, 8px);
  }

  svg {
    display: block;
    cursor: crosshair;
    touch-action: pan-y;
  }

  svg:focus-visible {
    outline: 2px solid var(--color-purple);
    outline-offset: -2px;
  }

  .grid {
    stroke: var(--color-border);
    stroke-width: 1;
  }

  .band {
    fill: var(--color-surface-elevated);
    opacity: 0.5;
  }

  .band-active {
    fill: var(--color-purple);
    opacity: 0.14;
  }

  .band-active.pinned {
    opacity: 0.24;
  }

  .gap-line {
    fill: none;
    stroke-width: 2.5;
    stroke-linejoin: round;
    stroke-linecap: round;
    vector-effect: non-scaling-stroke;
  }

  .terminus {
    stroke-width: 3;
    vector-effect: non-scaling-stroke;
  }

  .skull {
    fill: var(--color-danger);
  }

  .skull-count {
    fill: var(--color-danger);
    font-family: var(--font-mono);
    font-size: 10px;
  }

  .tick,
  .axis {
    fill: var(--color-text-secondary);
    font-family: var(--font-mono);
    font-size: 10px;
  }
</style>
