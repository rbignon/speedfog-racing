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
  let error = $state<string | null>(null);

  $effect(() => {
    loadData();
    loadTeasers();
  });

  async function loadData() {
    error = null;
    try {
      data = await fetchStatsOverview();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load overview.";
    }
  }

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

  // The four teaser slots render immediately as skeletons and each fills (or
  // hides, on failure/empty data) when its own fetch resolves, so a slow
  // sibling endpoint never holds the others back.
  type TeaserSlot = { value: string; sub: string } | "loading" | "hidden";
  const TEASER_DEFS = [
    { key: "bosses", label: "Deadliest boss", href: "/stats?tab=bosses" },
    { key: "zones", label: "Deadliest zone", href: "/stats?tab=zones" },
    { key: "weapons", label: "Top weapon", href: "/stats?tab=weapons" },
    {
      key: "players",
      label: "Most common play style",
      href: "/stats?tab=players",
    },
  ] as const;
  let teaserSlots = $state<Record<string, TeaserSlot>>({
    bosses: "loading",
    zones: "loading",
    weapons: "loading",
    players: "loading",
  });

  function loadTeasers() {
    fetchBossStats()
      .then((res) => {
        const top = res.bosses
          .slice()
          .sort((a, b) => b.avg_deaths - a.avg_deaths)[0];
        teaserSlots.bosses = top
          ? {
              value: top.display_name,
              sub: `${top.avg_deaths.toFixed(1)} avg deaths`,
            }
          : "hidden";
      })
      .catch(() => {
        teaserSlots.bosses = "hidden";
      });
    fetchZoneStats()
      .then((res) => {
        const top = res.deadliest[0];
        teaserSlots.zones = top
          ? {
              value: top.display_name,
              sub: `${top.avg_deaths_per_visit.toFixed(1)} avg deaths / visit`,
            }
          : "hidden";
      })
      .catch(() => {
        teaserSlots.zones = "hidden";
      });
    (async () => {
      await loadCatalogue();
      return fetchWeaponStats();
    })()
      .then((res) => {
        const top = res.combos
          .slice()
          .sort((a, b) => b.total_ticks - a.total_ticks)[0];
        teaserSlots.weapons = top
          ? {
              value: formatCombo(top.ids, getWeaponName),
              sub: `${formatIgt(top.total_ticks * 1000)} played`,
            }
          : "hidden";
      })
      .catch(() => {
        teaserSlots.weapons = "hidden";
      });
    fetchPlayerProfiles()
      .then((res) => {
        let best: { label: string; count: number } | null = null;
        for (const [key, list] of Object.entries(res.profiles)) {
          const label = TRAIT_LABELS[key];
          if (!label || list.length === 0) continue;
          if (!best || list.length > best.count)
            best = { label, count: list.length };
        }
        teaserSlots.players = best
          ? {
              value: best.label,
              sub: `${best.count} player${best.count === 1 ? "" : "s"}`,
            }
          : "hidden";
      })
      .catch(() => {
        teaserSlots.players = "hidden";
      });
  }

  function formatHours(h: number): string {
    if (h > 0 && h < 1) return "<1";
    return Math.round(h).toLocaleString();
  }

  // Labels and accents are static, so the four cards render immediately with
  // skeleton values and fill in when the overview endpoint responds.
  const TILE_DEFS = [
    {
      key: "races",
      label: "Total races",
      accent: "var(--color-gold)",
      accentSoft: "rgba(200, 164, 78, 0.32)",
    },
    {
      key: "players",
      label: "Active players",
      accent: "#4aae8c",
      accentSoft: "rgba(74, 174, 140, 0.36)",
    },
    {
      key: "deaths",
      label: "Total deaths",
      accent: "#dc6a51",
      accentSoft: "rgba(220, 106, 81, 0.36)",
    },
    {
      key: "hours",
      label: "Hours raced",
      accent: "var(--color-info)",
      accentSoft: "rgba(123, 162, 204, 0.36)",
    },
  ] as const;

  const tileData = $derived<Record<
    string,
    { value: string; series: number[] }
  > | null>(
    data
      ? {
          races: {
            value: data.kpis.total_races.toLocaleString(),
            series: data.weekly.races,
          },
          players: {
            value: data.kpis.active_players.toLocaleString(),
            series: data.weekly.active_users,
          },
          deaths: {
            value: data.kpis.total_deaths.toLocaleString(),
            series: data.weekly.deaths,
          },
          hours: {
            value: formatHours(data.kpis.hours_raced),
            series: data.weekly.hours,
          },
        }
      : null,
  );

  function barHeight(value: number, max: number): string {
    if (max === 0) return "2%";
    return `${Math.max(2, Math.round((value / max) * 100))}%`;
  }
</script>

{#if error}
  <p class="error-text">{error}</p>
{:else}
  <div class="cards">
    {#each TILE_DEFS as def (def.key)}
      {@const td = tileData?.[def.key]}
      <article
        class="card"
        style:--accent={def.accent}
        style:--accent-soft={def.accentSoft}
      >
        {#if td}
          {@const max = Math.max(1, ...td.series)}
          <span class="value">{td.value}</span>
          <span class="label">{def.label}</span>
          <div class="spark" aria-hidden="true">
            {#each td.series as v, i (i)}
              <span class="bar" style:height={barHeight(v, max)}></span>
            {/each}
          </div>
        {:else}
          <span class="skeleton skeleton-value" aria-hidden="true"></span>
          <span class="label">{def.label}</span>
          <div class="spark" aria-hidden="true"></div>
        {/if}
      </article>
    {/each}
  </div>
{/if}
{#if TEASER_DEFS.some((d) => teaserSlots[d.key] !== "hidden")}
  <div class="teasers">
    {#each TEASER_DEFS as def (def.key)}
      {@const slot = teaserSlots[def.key]}
      {#if slot !== "hidden"}
        <a class="teaser" href={def.href} data-sveltekit-noscroll>
          <span class="teaser-label">{def.label}</span>
          {#if slot === "loading"}
            <span class="skeleton skeleton-line" aria-hidden="true"></span>
            <span class="skeleton skeleton-sub" aria-hidden="true"></span>
          {:else}
            <span class="teaser-value">{slot.value}</span>
            <span class="teaser-sub">{slot.sub}</span>
          {/if}
        </a>
      {/if}
    {/each}
  </div>
{/if}
<div class="heatmap-slot">
  <ActivityHeatmap />
</div>

<style>
  .error-text {
    color: var(--color-danger);
    font-style: italic;
    padding: 2rem 0;
  }

  .skeleton {
    background: var(--color-border);
    border-radius: 4px;
    animation: skeleton-pulse 1.4s ease-in-out infinite;
  }

  @keyframes skeleton-pulse {
    0%,
    100% {
      opacity: 0.45;
    }
    50% {
      opacity: 0.9;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .skeleton {
      animation: none;
      opacity: 0.6;
    }
  }

  /* Skeletons approximate their real counterpart's box (exact for .value,
     which has line-height 1; a few px short for the teaser lines) so the
     layout barely shifts when values land. */
  .skeleton-value {
    height: var(--font-size-2xl);
    width: 4.5rem;
  }

  .skeleton-line {
    height: var(--font-size-lg);
    width: 70%;
  }

  .skeleton-sub {
    height: var(--font-size-xs);
    width: 45%;
    margin-top: auto;
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
    font-family: var(--font-mono);
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
