<script lang="ts">
  import type { UserPoolStatsEntry } from "$lib/api";
  import { formatPoolName } from "$lib/utils/format";
  import { formatIgt } from "$lib/utils/training";

  type PoolEntry = UserPoolStatsEntry & { pool_display_name?: string | null };

  let { pools }: { pools: PoolEntry[] } = $props();

  type Sortable = PoolEntry & { _displayName: string; _bestMs: number | null };

  function bestTime(entry: PoolEntry): number | null {
    const r = entry.race?.best_time_ms ?? null;
    const t = entry.training?.best_time_ms ?? null;
    if (r === null) return t;
    if (t === null) return r;
    return Math.min(r, t);
  }

  function displayName(entry: PoolEntry): string {
    return entry.pool_display_name || formatPoolName(entry.pool_name);
  }

  const ranked = $derived<Sortable[]>(
    pools
      .filter((p) => p.total_runs > 0)
      .map((p) => ({
        ...p,
        _displayName: displayName(p),
        _bestMs: bestTime(p),
      }))
      .sort((a, b) => {
        if (b.total_runs !== a.total_runs) return b.total_runs - a.total_runs;
        const ab = a._bestMs ?? Number.POSITIVE_INFINITY;
        const bb = b._bestMs ?? Number.POSITIVE_INFINITY;
        if (ab !== bb) return ab - bb;
        return a._displayName.localeCompare(b._displayName);
      }),
  );

  const hero = $derived(ranked[0] ?? null);
  const pills = $derived(ranked.slice(1));
</script>

{#if hero}
  <section class="mode-stats" class:single={pills.length === 0}>
    <div class="hero">
      <span class="tag">MOST PLAYED</span>
      <h3 class="name">{hero._displayName}</h3>
      <div class="hero-stats">
        <div class="hero-stat">
          <span class="hero-stat-label">Best Time</span>
          <span class="hero-stat-value gold"
            >{hero._bestMs !== null ? formatIgt(hero._bestMs) : "-"}</span
          >
        </div>
        <div class="hero-stat">
          <span class="hero-stat-label">Races</span>
          <span class="hero-stat-value">{hero.race?.runs ?? 0}</span>
        </div>
        <div class="hero-stat">
          <span class="hero-stat-label">Solo</span>
          <span class="hero-stat-value">{hero.training?.runs ?? 0}</span>
        </div>
      </div>
    </div>

    {#if pills.length > 0}
      <div class="pills">
        {#each pills as p (p.pool_name)}
          <div class="pill">
            <span class="pill-name">{p._displayName}</span>
            <span class="pill-runs"
              >{p.total_runs} {p.total_runs === 1 ? "run" : "runs"}</span
            >
            <span class="pill-best"
              >{p._bestMs !== null ? formatIgt(p._bestMs) : "-"}</span
            >
          </div>
        {/each}
      </div>
    {/if}
  </section>
{/if}

<style>
  .mode-stats {
    display: grid;
    grid-template-columns: 1.4fr 1fr;
    gap: 1rem;
    align-items: center;
    margin-bottom: 2.5rem;
  }

  .mode-stats.single {
    grid-template-columns: 1fr;
  }

  .hero {
    position: relative;
    padding: 1.5rem 1.5rem 1.4rem;
    background: linear-gradient(
      160deg,
      var(--color-surface) 0%,
      var(--color-surface-elevated) 100%
    );
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  .hero::before {
    content: "";
    position: absolute;
    top: -40%;
    right: -20%;
    width: 60%;
    height: 110%;
    background: radial-gradient(
      circle,
      rgba(200, 164, 78, 0.12),
      transparent 65%
    );
    pointer-events: none;
  }

  .tag {
    position: absolute;
    top: 1.1rem;
    right: 1.2rem;
    font-size: 0.62rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.14em;
    color: var(--color-gold);
    background: rgba(200, 164, 78, 0.12);
    padding: 0.22rem 0.5rem;
    border-radius: var(--radius-sm);
  }

  .name {
    margin: 0 0 1.1rem;
    font-size: 1.7rem;
    font-weight: 700;
    color: var(--color-text);
    letter-spacing: -0.015em;
  }

  .hero-stats {
    display: grid;
    grid-template-columns: repeat(3, 1fr);
    gap: 1rem;
  }

  .hero-stat {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }

  .hero-stat-label {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.13em;
    color: var(--color-text-secondary);
  }

  .hero-stat-value {
    font-size: 1.35rem;
    font-weight: 700;
    color: var(--color-text);
    font-variant-numeric: tabular-nums;
    letter-spacing: -0.01em;
  }

  .hero-stat-value.gold {
    color: var(--color-gold);
  }

  .pills {
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }

  .pill {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: 0.85rem;
    align-items: center;
    padding: 0.55rem 0.85rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    font-size: var(--font-size-sm);
    transition: border-color 0.15s ease;
  }

  .pill:hover {
    border-color: rgba(200, 164, 78, 0.35);
  }

  .pill-name {
    color: var(--color-text);
    font-weight: 500;
  }

  .pill-runs {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    font-variant-numeric: tabular-nums;
  }

  .pill-best {
    color: var(--color-gold);
    font-variant-numeric: tabular-nums;
    font-weight: 600;
  }

  @media (max-width: 720px) {
    .mode-stats {
      grid-template-columns: 1fr;
    }
  }
</style>
