<script lang="ts">
  import type { UserDailyStreakStats } from "$lib/api";

  let { myStreak }: { myStreak: UserDailyStreakStats | null } = $props();

  let show = $derived(myStreak !== null && myStreak.current > 0);
</script>

{#if show && myStreak}
  <span class="streak-indicator">
    🔥 {myStreak.current}-day streak
    {#if myStreak.freeze_count > 0}
      · ❄️ {myStreak.freeze_count} freeze{myStreak.freeze_count > 1 ? "s" : ""}
    {/if}
  </span>
{/if}

<style>
  .streak-indicator {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    font-variant-numeric: tabular-nums;
  }
  @media (max-width: 640px) {
    .streak-indicator {
      display: none;
    }
  }
</style>
