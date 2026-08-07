<script lang="ts">
  import { fetchZoneStats, type ZoneStatsResponse } from "$lib/api";

  let data = $state<ZoneStatsResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let deadliest = $derived(data?.deadliest ?? []);
  let mostBacktracked = $derived(data?.most_backtracked ?? []);
  let slowest = $derived(data?.slowest ?? []);
  let fastest = $derived(data?.fastest ?? []);

  let maxDeaths = $derived(
    Math.max(1, ...deadliest.map((z) => z.avg_deaths_per_visit)),
  );
  let maxBacktracks = $derived(
    Math.max(0.01, ...mostBacktracked.map((z) => z.backtrack_rate)),
  );
  let maxTime = $derived(Math.max(1, ...slowest.map((z) => z.median_time_ms)));
  let maxFastTime = $derived(
    Math.max(1, ...fastest.map((z) => z.median_time_ms)),
  );

  $effect(() => {
    loadData();
  });

  async function loadData() {
    loading = true;
    error = null;
    try {
      data = await fetchZoneStats();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load zone stats.";
    } finally {
      loading = false;
    }
  }

  function barWidth(value: number, max: number): string {
    return `${Math.max(4, (value / max) * 100)}%`;
  }

  function typeBadgeClass(type: string): string {
    if (type === "legacy_dungeon") return "type-badge-legacy";
    return "type-badge-mini";
  }

  function typeLabel(type: string): string {
    if (type === "legacy_dungeon") return "Legacy";
    return "Minor";
  }

  function formatTime(ms: number): string {
    const totalSeconds = Math.round(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  }
</script>

<div class="tab-header">
  <a href="/zones" class="see-all-link"
    >Zone codex <span aria-hidden="true">&rarr;</span></a
  >
</div>

{#if loading}
  <p class="loading-text">Loading zone stats...</p>
{:else if error}
  <p class="error-text">{error}</p>
{:else}
  <div class="zones-layout">
    <div class="zone-panel">
      <h2>Deadliest Zones</h2>
      <p class="panel-subtitle">avg. deaths per visit</p>
      {#if deadliest.length === 0}
        <p class="empty">No data yet.</p>
      {:else}
        <div class="zone-list">
          {#each deadliest as zone}
            <a href="/zones?zone={zone.node_id}" class="zone-row">
              <div class="zone-header">
                <span class="zone-name">{zone.display_name}</span>
                <span class="type-badge {typeBadgeClass(zone.type)}"
                  >{typeLabel(zone.type)}</span
                >
              </div>
              <div class="bar-row">
                <div
                  class="bar bar-death"
                  style="width: {barWidth(
                    zone.avg_deaths_per_visit,
                    maxDeaths,
                  )}"
                ></div>
                <span class="bar-value"
                  >{zone.avg_deaths_per_visit.toFixed(1)}</span
                >
              </div>
            </a>
          {/each}
        </div>
      {/if}
    </div>

    <div class="zone-panel">
      <h2>Most Backtracked</h2>
      <p class="panel-subtitle">share of visits ending in a turn-away</p>
      {#if mostBacktracked.length === 0}
        <p class="empty">No data yet.</p>
      {:else}
        <div class="zone-list">
          {#each mostBacktracked as zone}
            <a href="/zones?zone={zone.node_id}" class="zone-row">
              <div class="zone-header">
                <span class="zone-name">{zone.display_name}</span>
                <span class="type-badge {typeBadgeClass(zone.type)}"
                  >{typeLabel(zone.type)}</span
                >
              </div>
              <div class="bar-row">
                <div
                  class="bar bar-backtrack"
                  style="width: {barWidth(zone.backtrack_rate, maxBacktracks)}"
                ></div>
                <span class="bar-value"
                  >{Math.round(zone.backtrack_rate * 100)}%</span
                >
              </div>
            </a>
          {/each}
        </div>
      {/if}
    </div>

    <div class="zone-panel">
      <h2>Slowest Zones</h2>
      <p class="panel-subtitle">median clear time</p>
      {#if slowest.length === 0}
        <p class="empty">No data yet.</p>
      {:else}
        <div class="zone-list">
          {#each slowest as zone}
            <a href="/zones?zone={zone.node_id}" class="zone-row">
              <div class="zone-header">
                <span class="zone-name">{zone.display_name}</span>
                <span class="type-badge {typeBadgeClass(zone.type)}"
                  >{typeLabel(zone.type)}</span
                >
              </div>
              <div class="bar-row">
                <div
                  class="bar bar-time"
                  style="width: {barWidth(zone.median_time_ms, maxTime)}"
                ></div>
                <span class="bar-value">{formatTime(zone.median_time_ms)}</span>
              </div>
            </a>
          {/each}
        </div>
      {/if}
    </div>

    <div class="zone-panel">
      <h2>Fastest Zones</h2>
      <p class="panel-subtitle">median clear time</p>
      {#if fastest.length === 0}
        <p class="empty">No data yet.</p>
      {:else}
        <div class="zone-list">
          {#each fastest as zone}
            <a href="/zones?zone={zone.node_id}" class="zone-row">
              <div class="zone-header">
                <span class="zone-name">{zone.display_name}</span>
                <span class="type-badge {typeBadgeClass(zone.type)}"
                  >{typeLabel(zone.type)}</span
                >
              </div>
              <div class="bar-row">
                <div
                  class="bar bar-fast"
                  style="width: {barWidth(zone.median_time_ms, maxFastTime)}"
                ></div>
                <span class="bar-value">{formatTime(zone.median_time_ms)}</span>
              </div>
            </a>
          {/each}
        </div>
      {/if}
    </div>
  </div>
{/if}

<style>
  .tab-header {
    display: flex;
    justify-content: flex-end;
    margin-bottom: 0.75rem;
  }

  .see-all-link {
    color: var(--color-text-secondary);
    text-decoration: none;
    font-size: var(--font-size-sm);
    transition: color 0.15s ease;
  }

  .see-all-link:hover {
    color: var(--color-purple);
  }

  .loading-text,
  .error-text {
    color: var(--color-text-disabled);
    font-style: italic;
    padding: 2rem 0;
  }

  .error-text {
    color: var(--color-danger);
  }

  .empty {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .zones-layout {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.5rem;
  }

  .zone-panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1.25rem;
  }

  .zone-panel h2 {
    margin: 0;
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--color-gold);
  }

  .panel-subtitle {
    margin: 0.15rem 0 1rem 0;
    font-size: var(--font-size-xs);
    color: var(--color-text-disabled);
  }

  .zone-list {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .zone-row {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    color: inherit;
    text-decoration: none;
  }

  .zone-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .zone-name {
    font-weight: 500;
    font-size: var(--font-size-base);
    transition: color var(--transition);
  }

  .zone-row:hover .zone-name {
    color: var(--color-purple);
  }

  .type-badge {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.1rem 0.4rem;
    border-radius: var(--radius-sm);
  }

  .type-badge-legacy {
    background: rgba(200, 164, 78, 0.2);
    color: var(--color-gold);
  }

  .type-badge-mini {
    background: rgba(107, 114, 128, 0.2);
    color: var(--color-text-secondary);
  }

  .bar-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .bar {
    height: 10px;
    border-radius: 5px;
    transition: width 0.3s ease;
  }

  .bar-death {
    background: var(--color-danger);
  }

  .bar-backtrack {
    background: var(--color-purple);
  }

  .bar-time {
    background: var(--color-gold);
  }

  .bar-fast {
    background: var(--color-success);
  }

  .bar-value {
    font-size: var(--font-size-sm);
    font-family: var(--font-mono);
    color: var(--color-text-secondary);
    flex-shrink: 0;
  }

  @media (max-width: 768px) {
    .zones-layout {
      grid-template-columns: 1fr;
    }
  }
</style>
