<script lang="ts">
  import type { UserProfile } from "$lib/api";

  type CategoryKey = "races" | "daily" | "solo" | "organized";

  let {
    profile,
    links,
  }: {
    profile: UserProfile;
    links?: Partial<Record<CategoryKey, string>>;
  } = $props();

  type Category = {
    key: CategoryKey;
    label: string;
    value: number;
    series: number[];
    accent: string;
    accentSoft: string;
    emptyCopy: string;
  };

  const categories = $derived<Category[]>([
    {
      key: "races",
      label: "Races",
      value: profile.stats.race_count,
      series: profile.stats.weekly.races,
      accent: "var(--color-gold)",
      accentSoft: "rgba(200, 164, 78, 0.32)",
      emptyCopy: "Never raced",
    },
    {
      key: "daily",
      label: "Daily",
      value: profile.stats.daily_count,
      series: profile.stats.weekly.daily,
      accent: "#2dd4bf",
      accentSoft: "rgba(45, 212, 191, 0.36)",
      emptyCopy: "Never daily",
    },
    {
      key: "solo",
      label: "Solo",
      value: profile.stats.training_count,
      series: profile.stats.weekly.solo,
      accent: "var(--color-purple)",
      accentSoft: "rgba(139, 92, 246, 0.36)",
      emptyCopy: "Never solo",
    },
    {
      key: "organized",
      label: "Organized",
      value: profile.stats.organized_count,
      series: profile.stats.weekly.organized,
      accent: "#f59e0b",
      accentSoft: "rgba(245, 158, 11, 0.36)",
      emptyCopy: "Never organized",
    },
  ]);

  function barHeight(value: number, max: number): string {
    if (max === 0) return "2%";
    return `${Math.max(2, Math.round((value / max) * 100))}%`;
  }
</script>

<div class="cards">
  {#each categories as cat (cat.key)}
    {@const max = Math.max(1, ...cat.series)}
    {@const empty = cat.value === 0}
    {@const href = links?.[cat.key]}
    {#if href}
      <a
        class="card card-link"
        {href}
        style:--accent={cat.accent}
        style:--accent-soft={cat.accentSoft}
      >
        <span class="value" class:muted={empty}>{cat.value}</span>
        <span class="label">{cat.label}</span>
        {#if empty}
          <div class="empty">{cat.emptyCopy}</div>
        {:else}
          <div class="spark" aria-hidden="true">
            {#each cat.series as v, i (i)}
              <span class="bar" style:height={barHeight(v, max)}></span>
            {/each}
          </div>
        {/if}
      </a>
    {:else}
      <article
        class="card"
        style:--accent={cat.accent}
        style:--accent-soft={cat.accentSoft}
      >
        <span class="value" class:muted={empty}>{cat.value}</span>
        <span class="label">{cat.label}</span>
        {#if empty}
          <div class="empty">{cat.emptyCopy}</div>
        {:else}
          <div class="spark" aria-hidden="true">
            {#each cat.series as v, i (i)}
              <span class="bar" style:height={barHeight(v, max)}></span>
            {/each}
          </div>
        {/if}
      </article>
    {/if}
  {/each}
</div>

<style>
  .cards {
    display: grid;
    grid-template-columns: repeat(4, 1fr);
    gap: 0.85rem;
    margin-bottom: 2rem;
  }

  .card {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    padding: 1.1rem 1.15rem 1rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .card-link {
    text-decoration: none;
    color: inherit;
    transition:
      border-color 0.18s ease,
      transform 0.18s ease;
  }

  .card-link:hover {
    border-color: var(--accent-soft);
    transform: translateY(-1px);
  }

  .value {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    line-height: 1;
    font-variant-numeric: tabular-nums;
    color: var(--accent);
    letter-spacing: -0.02em;
  }

  .value.muted {
    color: var(--color-text-disabled);
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

  .empty {
    margin-top: 0.55rem;
    height: 32px;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px dashed var(--color-border);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    color: var(--color-text-disabled);
    font-style: italic;
  }

  @media (max-width: 640px) {
    .cards {
      grid-template-columns: repeat(2, 1fr);
    }
  }
</style>
