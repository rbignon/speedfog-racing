<script lang="ts">
  import { onMount } from "svelte";
  import type { Race } from "$lib/api";
  import {
    dailyCloseLabel,
    dailyPathForDate,
    dailyTheme,
    dailyUserResultPreview,
    dailyUserStatus,
    dailyWinner,
  } from "$lib/daily";

  interface Props {
    today: Race | null;
    recent: Race[];
    userId: string | null | undefined;
  }

  let { today, recent, userId }: Props = $props();

  let now = $state(Date.now());
  onMount(() => {
    const timer = setInterval(() => (now = Date.now()), 60_000);
    return () => clearInterval(timer);
  });

  let countdown = $derived(today ? dailyCloseLabel(today.race_ends_at, now) : null);
</script>

<section class="dashboard-section">
  <div class="section-header">
    <h2>Daily Seed</h2>
  </div>
  {#if today}
    <a class="daily-card" href="/daily">
      <div class="card-row">
        <strong>Today's Daily</strong>
        {#if countdown}
          <span class="countdown">{countdown}</span>
        {/if}
      </div>
      <span>{dailyTheme(today)}</span>
      <span class="status">{dailyUserStatus(today)}</span>
    </a>
  {:else}
    <div class="empty-card">No daily seed today.</div>
  {/if}

  {#if recent.length > 0}
    <ul class="recent-dailies">
      {#each recent as race (race.id)}
        {@const winner = dailyWinner(race)}
        {@const userResult = dailyUserResultPreview(race, userId)}
        <li>
          <a class="recent-link" href={dailyPathForDate(race.daily_date!)}>
            <span class="date">{race.daily_date}</span>
            <span class="theme">· {dailyTheme(race)}</span>
            {#if winner}
              <span class="winner">
                · 🥇 {winner.twitch_display_name ?? winner.twitch_username}
              </span>
            {/if}
            {#if userResult}
              <span class="user-result">· you: {userResult}</span>
            {/if}
          </a>
        </li>
      {/each}
    </ul>
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

  .card-row {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.5rem;
  }

  .countdown {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
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
    margin: 0.75rem 0 0;
    padding: 0;
    list-style: none;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .recent-link {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    color: var(--color-text-secondary);
    text-decoration: none;
    font-size: var(--font-size-sm);
  }

  .recent-link:hover {
    color: var(--color-purple);
  }

  .recent-link .date {
    color: var(--color-text);
    font-variant-numeric: tabular-nums;
  }

  .recent-link .theme {
    color: var(--color-text-disabled);
  }

  .recent-link .winner {
    color: var(--color-gold);
  }

  .recent-link .user-result {
    color: var(--color-purple);
  }
</style>
