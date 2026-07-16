<script lang="ts">
  import { fetchStatsOverview, type StatsOverviewResponse } from "$lib/api";

  let data = $state<StatsOverviewResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  $effect(() => {
    loadData();
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

  function formatHours(h: number): string {
    if (h > 0 && h < 1) return "<1";
    return Math.round(h).toLocaleString();
  }

  type Tile = {
    key: string;
    label: string;
    value: string;
    series: number[];
    accent: string;
    accentSoft: string;
  };

  const tiles = $derived<Tile[]>(
    data
      ? [
          {
            key: "races",
            label: "Total races",
            value: data.kpis.total_races.toLocaleString(),
            series: data.weekly.races,
            accent: "var(--color-gold)",
            accentSoft: "rgba(200, 164, 78, 0.32)",
          },
          {
            key: "players",
            label: "Active players",
            value: data.kpis.active_players.toLocaleString(),
            series: data.weekly.active_users,
            accent: "#22c55e",
            accentSoft: "rgba(34, 197, 94, 0.36)",
          },
          {
            key: "deaths",
            label: "Total deaths",
            value: data.kpis.total_deaths.toLocaleString(),
            series: data.weekly.deaths,
            accent: "#ef4444",
            accentSoft: "rgba(239, 68, 68, 0.36)",
          },
          {
            key: "hours",
            label: "Hours raced",
            value: formatHours(data.kpis.hours_raced),
            series: data.weekly.hours,
            accent: "var(--color-purple)",
            accentSoft: "rgba(139, 92, 246, 0.36)",
          },
        ]
      : [],
  );

  function barHeight(value: number, max: number): string {
    if (max === 0) return "2%";
    return `${Math.max(2, Math.round((value / max) * 100))}%`;
  }
</script>

{#if loading}
  <p class="loading-text">Loading overview...</p>
{:else if error}
  <p class="error-text">{error}</p>
{:else if data}
  <div class="cards">
    {#each tiles as tile (tile.key)}
      {@const max = Math.max(1, ...tile.series)}
      <article
        class="card"
        style:--accent={tile.accent}
        style:--accent-soft={tile.accentSoft}
      >
        <span class="value">{tile.value}</span>
        <span class="label">{tile.label}</span>
        <div class="spark" aria-hidden="true">
          {#each tile.series as v, i (i)}
            <span class="bar" style:height={barHeight(v, max)}></span>
          {/each}
        </div>
      </article>
    {/each}
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

  .cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.85rem;
  }

  .card {
    position: relative;
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 1.1rem 1.15rem 1rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .value {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    line-height: 1;
    font-variant-numeric: tabular-nums;
    color: var(--accent);
    letter-spacing: -0.02em;
  }

  .label {
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    letter-spacing: 0.13em;
    color: var(--color-text-secondary);
    font-weight: 600;
  }

  .spark {
    margin-top: 0.55rem;
    height: 32px;
    display: flex;
    align-items: flex-end;
    gap: 2px;
  }

  .bar {
    flex: 1;
    background: var(--accent-soft);
    border-radius: 1px;
    min-height: 2px;
  }

  @media (max-width: 640px) {
    .cards {
      grid-template-columns: repeat(2, 1fr);
    }
  }
</style>
