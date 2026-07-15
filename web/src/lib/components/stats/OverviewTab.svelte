<script lang="ts">
  import { fetchStatsOverview, type StatsOverviewResponse } from "$lib/api";
  import { Chart, registerables } from "chart.js";
  Chart.register(...registerables);

  let data = $state<StatsOverviewResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let racesCanvas = $state<HTMLCanvasElement | null>(null);
  let playersCanvas = $state<HTMLCanvasElement | null>(null);
  let deathsCanvas = $state<HTMLCanvasElement | null>(null);
  let hoursCanvas = $state<HTMLCanvasElement | null>(null);
  let charts: Chart[] = [];

  $effect(() => {
    loadData();
    return () => {
      charts.forEach((c) => c.destroy());
      charts = [];
    };
  });

  async function loadData() {
    loading = true;
    error = null;
    try {
      data = await fetchStatsOverview();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load overview.";
    } finally {
      loading = false;
    }
  }

  $effect(() => {
    if (
      !data ||
      !racesCanvas ||
      !playersCanvas ||
      !deathsCanvas ||
      !hoursCanvas
    )
      return;
    renderCharts($state.snapshot(data));
  });

  function miniBar(
    canvas: HTMLCanvasElement,
    labels: string[],
    values: number[],
    rgb: string,
  ) {
    charts.push(
      new Chart(canvas, {
        type: "bar",
        data: {
          labels,
          datasets: [
            {
              data: values,
              backgroundColor: `rgba(${rgb},0.6)`,
              borderColor: `rgb(${rgb})`,
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          maintainAspectRatio: false,
          plugins: { legend: { display: false } },
          scales: {
            x: {
              grid: { display: false },
              ticks: { color: "#888", font: { size: 9 } },
            },
            y: {
              beginAtZero: true,
              grid: { color: "rgba(255,255,255,0.06)" },
              ticks: { color: "#888", font: { size: 9 }, maxTicksLimit: 4 },
            },
          },
        },
      }),
    );
  }

  function renderCharts(d: StatsOverviewResponse) {
    charts.forEach((c) => c.destroy());
    charts = [];
    miniBar(racesCanvas!, d.weekly.weeks, d.weekly.races, "200,164,78");
    miniBar(playersCanvas!, d.weekly.weeks, d.weekly.active_users, "34,197,94");
    miniBar(deathsCanvas!, d.weekly.weeks, d.weekly.deaths, "239,68,68");
    miniBar(hoursCanvas!, d.weekly.weeks, d.weekly.hours, "139,92,246");
  }

  function formatHours(h: number): string {
    if (h > 0 && h < 1) return "<1";
    return h.toFixed(0);
  }
</script>

{#if loading}
  <p class="loading-text">Loading overview...</p>
{:else if error}
  <p class="error-text">{error}</p>
{:else if data}
  <div class="kpi-grid">
    <div class="kpi-tile">
      <span class="kpi-label">Total races</span>
      <span class="kpi-value">{data.kpis.total_races.toLocaleString()}</span>
      <div class="kpi-chart"><canvas bind:this={racesCanvas}></canvas></div>
    </div>
    <div class="kpi-tile">
      <span class="kpi-label">Active players</span>
      <span class="kpi-value">{data.kpis.active_players.toLocaleString()}</span>
      <div class="kpi-chart"><canvas bind:this={playersCanvas}></canvas></div>
    </div>
    <div class="kpi-tile">
      <span class="kpi-label">Total deaths</span>
      <span class="kpi-value">{data.kpis.total_deaths.toLocaleString()}</span>
      <div class="kpi-chart"><canvas bind:this={deathsCanvas}></canvas></div>
    </div>
    <div class="kpi-tile">
      <span class="kpi-label">Hours raced</span>
      <span class="kpi-value">{formatHours(data.kpis.hours_raced)}</span>
      <div class="kpi-chart"><canvas bind:this={hoursCanvas}></canvas></div>
    </div>
  </div>
{/if}

<style>
  .loading-text,
  .error-text {
    color: var(--color-text-disabled);
    font-style: italic;
    padding: 2rem 0;
  }

  .error-text {
    color: var(--color-danger);
  }

  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
  }

  .kpi-tile {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1rem 1.25rem;
  }

  .kpi-label {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .kpi-value {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    color: var(--color-text);
  }

  .kpi-chart {
    position: relative;
    height: 90px;
    margin-top: 0.5rem;
  }

  @media (max-width: 640px) {
    .kpi-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
