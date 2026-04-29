<script lang="ts">
  import type { Race, RaceDetail } from "$lib/api";
  import { dailyPathForDate, dailyTheme, dailyUserStatus } from "$lib/daily";

  interface Props {
    today: RaceDetail | null;
    recent: Race[];
    userId: string | null | undefined;
  }

  let { today, recent, userId }: Props = $props();
</script>

<section class="dashboard-section">
  <div class="section-header">
    <h2>Daily Seed</h2>
  </div>
  {#if today}
    <a class="daily-card" href="/daily">
      <strong>Today's Daily</strong>
      <span>{dailyTheme(today)}</span>
      <span class="status">{dailyUserStatus(today, userId)}</span>
    </a>
  {:else}
    <div class="empty-card">No daily seed today.</div>
  {/if}

  {#if recent.length > 0}
    <div class="recent-dailies">
      {#each recent as race (race.id)}
        <a class="recent-link" href={dailyPathForDate(race.daily_date!)}>
          <span>{race.daily_date}</span>
          <span class="theme">· {dailyTheme(race)}</span>
        </a>
      {/each}
    </div>
  {/if}
</section>

<style>
  .dashboard-section {
    margin-bottom: 1.5rem;
  }

  .section-header {
    display: flex;
    align-items: center;
    margin-bottom: 0.75rem;
  }

  .section-header h2 {
    margin: 0;
    font-size: var(--font-size-lg);
  }

  .daily-card {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.875rem 1rem;
    border: 1px solid var(--color-gold);
    border-radius: var(--radius-md);
    background: rgba(234, 179, 8, 0.04);
    color: var(--color-text);
    text-decoration: none;
    transition: border-color var(--transition);
  }

  .daily-card:hover {
    border-color: var(--color-gold-hover);
  }

  .daily-card strong {
    color: var(--color-gold);
  }

  .daily-card .status {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .empty-card {
    padding: 0.875rem 1rem;
    border: 1px dashed var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text-secondary);
  }

  .recent-dailies {
    margin-top: 0.75rem;
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem 1rem;
  }

  .recent-link {
    color: var(--color-text-secondary);
    text-decoration: none;
    font-size: var(--font-size-sm);
  }

  .recent-link:hover {
    color: var(--color-purple);
  }

  .recent-link .theme {
    color: var(--color-text-disabled);
    margin-left: 0.25rem;
  }
</style>
