<script lang="ts">
  import { fetchActivityHeatmap, type HeatmapResponse } from "$lib/api";

  let data = $state<HeatmapResponse | null>(null);
  let loading = $state(true);

  const HOURS = [
    "00h",
    "02h",
    "04h",
    "06h",
    "08h",
    "10h",
    "12h",
    "14h",
    "16h",
    "18h",
    "20h",
    "22h",
  ];
  const DAYS = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"];

  $effect(() => {
    loadData();
  });

  async function loadData() {
    loading = true;
    try {
      const tz = Intl.DateTimeFormat().resolvedOptions().timeZone;
      data = await fetchActivityHeatmap(tz);
    } catch {
      data = null;
    } finally {
      loading = false;
    }
  }
</script>

{#if loading}
  <p class="loading-text">Loading activity...</p>
{:else if data}
  {@const max = Math.max(1, ...data.grid.flat())}
  <section class="heatmap-panel">
    <h2>Community Activity</h2>
    <div class="heatmap-grid">
      <div class="heatmap-corner"></div>
      {#each DAYS as day}
        <div class="heatmap-day">{day}</div>
      {/each}
      {#each HOURS as hour, rowIdx}
        <div class="heatmap-hour">{hour}</div>
        {#each data.grid[rowIdx] as val}
          <div
            class="heatmap-cell"
            style="background: rgba(200,164,78,{(val / max) * 0.9})"
            title={String(val)}
          ></div>
        {/each}
      {/each}
    </div>
    <div class="heatmap-legend">
      <span>0</span>
      <div class="heatmap-legend-bar"></div>
      <span>{max}</span>
    </div>
    <p class="heatmap-caption">
      Races, dailies, and solo sessions over the last {data.weeks} weeks. Times shown
      in {data.timezone}.
    </p>
  </section>
{/if}

<style>
  .loading-text {
    color: var(--color-text-disabled);
    font-style: italic;
    padding: 1rem 0;
  }

  .heatmap-panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.25rem 0.85rem;
  }

  .heatmap-panel h2 {
    margin: 0 0 0.75rem 0;
    font-size: var(--font-size-base);
    font-weight: 600;
    color: var(--color-text);
  }

  .heatmap-grid {
    display: grid;
    grid-template-columns: 2.5rem repeat(7, 1fr);
    gap: 3px;
  }

  .heatmap-corner {
    display: block;
  }

  .heatmap-day {
    text-align: center;
    font-size: 0.6rem;
    color: var(--color-text-secondary);
    padding-bottom: 2px;
  }

  .heatmap-hour {
    text-align: right;
    padding-right: 4px;
    font-size: 0.6rem;
    color: var(--color-text-secondary);
    line-height: 1.5rem;
  }

  .heatmap-cell {
    height: 1.5rem;
    border-radius: 2px;
    background: var(--color-bg, #0d1117);
  }

  .heatmap-legend {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 0.5rem;
    font-size: 0.6rem;
    color: var(--color-text-secondary);
  }

  .heatmap-legend-bar {
    flex: 1;
    height: 8px;
    border-radius: 4px;
    max-width: 120px;
    background: linear-gradient(to right, #0d1117, rgba(200, 164, 78, 0.9));
  }

  .heatmap-caption {
    margin: 0.5rem 0 0 0;
    font-size: var(--font-size-xs);
    color: var(--color-text-disabled);
  }
</style>
