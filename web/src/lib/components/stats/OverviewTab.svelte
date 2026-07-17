<script lang="ts">
  import {
    fetchStatsOverview,
    type StatsOverviewResponse,
    fetchBossStats,
    fetchZoneStats,
    fetchWeaponStats,
    fetchPlayerProfiles,
  } from "$lib/api";
  import {
    loadCatalogue,
    getWeaponName,
  } from "$lib/stores/weaponsCatalogue.svelte";
  import { formatCombo } from "$lib/weapons";
  import { formatIgt } from "$lib/utils/training";
  import ActivityHeatmap from "$lib/components/stats/ActivityHeatmap.svelte";

  let data = $state<StatsOverviewResponse | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);

  $effect(() => {
    loadData();
    loadTeasers();
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

  type Teaser = {
    key: string;
    label: string;
    value: string;
    sub: string;
    href: string;
  };

  let teasers = $state<Teaser[]>([]);

  // Labels mirror the TRAITS list in PlayersTab.svelte.
  const TRAIT_LABELS: Record<string, string> = {
    rusher: "Rusher",
    cautious: "Cautious",
    boss_slayer: "Boss Slayer",
    resilient: "Resilient",
    explorer: "Explorer",
    pathfinder: "Pathfinder",
    rage_quitter: "Rage Quitter",
  };

  async function loadTeasers() {
    const [bosses, zones, weapons, players] = await Promise.allSettled([
      fetchBossStats(),
      fetchZoneStats(),
      (async () => {
        await loadCatalogue();
        return fetchWeaponStats();
      })(),
      fetchPlayerProfiles(),
    ]);
    const items: Teaser[] = [];
    if (bosses.status === "fulfilled" && bosses.value.bosses.length > 0) {
      const top = bosses.value.bosses
        .slice()
        .sort((a, b) => b.avg_deaths - a.avg_deaths)[0];
      items.push({
        key: "bosses",
        label: "Deadliest boss",
        value: top.display_name,
        sub: `${top.avg_deaths.toFixed(1)} avg deaths`,
        href: "/stats?tab=bosses",
      });
    }
    if (zones.status === "fulfilled" && zones.value.deadliest.length > 0) {
      const top = zones.value.deadliest[0];
      items.push({
        key: "zones",
        label: "Deadliest zone",
        value: top.display_name,
        sub: `${top.avg_deaths_per_visit.toFixed(1)} avg deaths / visit`,
        href: "/stats?tab=zones",
      });
    }
    if (weapons.status === "fulfilled" && weapons.value.combos.length > 0) {
      const top = weapons.value.combos
        .slice()
        .sort((a, b) => b.total_ticks - a.total_ticks)[0];
      items.push({
        key: "weapons",
        label: "Top weapon combo",
        value: formatCombo(top.ids, getWeaponName),
        sub: `${formatIgt(top.total_ticks * 1000)} played`,
        href: "/stats?tab=weapons",
      });
    }
    if (players.status === "fulfilled") {
      let best: { label: string; count: number } | null = null;
      for (const [key, list] of Object.entries(players.value.profiles)) {
        const label = TRAIT_LABELS[key];
        if (!label || list.length === 0) continue;
        if (!best || list.length > best.count)
          best = { label, count: list.length };
      }
      if (best) {
        items.push({
          key: "players",
          label: "Most common play style",
          value: best.label,
          sub: `${best.count} player${best.count === 1 ? "" : "s"}`,
          href: "/stats?tab=players",
        });
      }
    }
    teasers = items;
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
  {#if teasers.length > 0}
    <div class="teasers">
      {#each teasers as t (t.key)}
        <a class="teaser" href={t.href} data-sveltekit-noscroll>
          <span class="teaser-label">{t.label}</span>
          <span class="teaser-value">{t.value}</span>
          <span class="teaser-sub">{t.sub}</span>
        </a>
      {/each}
    </div>
  {/if}
  <div class="heatmap-slot">
    <ActivityHeatmap />
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

  .teasers {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.85rem;
    margin-top: 0.85rem;
  }

  .teaser {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
    padding: 0.9rem 1.15rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    text-decoration: none;
    color: inherit;
    transition:
      border-color 0.18s ease,
      transform 0.18s ease;
  }

  .teaser:hover {
    border-color: rgba(200, 164, 78, 0.32);
    transform: translateY(-1px);
  }

  .teaser-label {
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    letter-spacing: 0.13em;
    color: var(--color-text-secondary);
    font-weight: 600;
  }

  .teaser-value {
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--color-text);
  }

  .teaser-sub {
    /* Grid rows stretch cards to equal height; pin the sub-stat to the
       bottom so all four align even when a value wraps to two lines. */
    margin-top: auto;
    font-size: var(--font-size-xs);
    color: var(--color-text-disabled);
  }

  .heatmap-slot {
    margin-top: 0.85rem;
  }

  @media (max-width: 640px) {
    .teasers {
      grid-template-columns: repeat(2, 1fr);
    }
  }
</style>
