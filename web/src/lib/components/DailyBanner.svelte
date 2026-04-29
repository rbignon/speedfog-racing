<script lang="ts">
  import type { Race } from "$lib/api";
  import { dailyTheme, fastestFinishedIgt } from "$lib/daily";
  import { formatIgt } from "$lib/utils/training";

  interface Props {
    race: Race;
    now: number;
  }

  let { race, now }: Props = $props();

  let finishedCount = $derived(
    race.participant_previews.filter((p) => p.status === "finished").length,
  );
  let fastest = $derived(fastestFinishedIgt(race.participant_previews));
  let closesAt = $derived(race.race_ends_at ? new Date(race.race_ends_at).getTime() : null);
  let remainingMs = $derived(closesAt ? Math.max(0, closesAt - now) : 0);
  let hours = $derived(Math.floor(remainingMs / 3_600_000));
  let minutes = $derived(Math.floor((remainingMs % 3_600_000) / 60_000));
</script>

<a class="daily-banner" href="/daily">
  <div class="daily-info">
    <strong>Daily Seed - {dailyTheme(race)}</strong>
    <span class="daily-stats">
      {finishedCount} finishers
      {#if fastest != null}, fastest {formatIgt(fastest)}{/if}
    </span>
  </div>
  <div class="daily-actions">
    <span class="btn btn-primary">Play now</span>
    {#if closesAt != null}
      <span class="countdown">Closes in {hours}h {minutes}m</span>
    {/if}
  </div>
</a>

<style>
  .daily-banner {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    align-items: center;
    justify-content: space-between;
    padding: 1rem 1.25rem;
    margin-bottom: 1.5rem;
    border: 1px solid var(--color-gold);
    border-radius: var(--radius-md);
    background: linear-gradient(
      90deg,
      rgba(234, 179, 8, 0.08),
      rgba(234, 179, 8, 0.02)
    );
    color: var(--color-text);
    text-decoration: none;
    transition: border-color var(--transition);
  }

  .daily-banner:hover {
    border-color: var(--color-gold-hover);
  }

  .daily-info {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .daily-info strong {
    color: var(--color-gold);
  }

  .daily-stats {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .daily-actions {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .countdown {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
</style>
