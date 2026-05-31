<script lang="ts">
  import type { WeeklyLeaderboardResponse } from "$lib/api";
  import UserLink from "$lib/components/UserLink.svelte";
  import WeaponsPopover from "$lib/components/WeaponsPopover.svelte";

  interface Props {
    data: WeeklyLeaderboardResponse;
    currentUserId?: string | null;
  }

  const { data, currentUserId = null }: Props = $props();

  const isEmpty = $derived(data.entries.length === 0);
  const isAwaitingFirstResults = $derived(isEmpty && data.dailies_total === 0);
  const isPastWithNoQualified = $derived(isEmpty && data.dailies_total > 0);
</script>

<div class="week-leaderboard">
  {#if isAwaitingFirstResults}
    <p class="empty">Weekly leaderboard updates as dailies close.</p>
  {:else if isPastWithNoQualified}
    <p class="empty">No qualified runs that week.</p>
  {:else}
    <ol class="list">
      {#each data.entries as entry (entry.user.id)}
        <li
          class="row"
          class:me={currentUserId !== null && entry.user.id === currentUserId}
        >
          <span
            class="rank"
            class:rank-gold={entry.rank === 1}
            class:rank-silver={entry.rank === 2}
            class:rank-bronze={entry.rank === 3}>{entry.rank}</span
          >
          <div class="middle">
            <div class="name-line">
              <UserLink user={entry.user} showBadge showAvatar />
            </div>
            <div class="sub-left">
              {entry.dailies_played} / {data.dailies_total}
            </div>
          </div>
          <div class="right">
            <div class="points">{entry.total_points} pts</div>
            <div class="sub-right">
              {#if entry.total_deaths > 0}
                <span class="deaths">{entry.total_deaths}</span>
              {/if}
              {#if entry.weapon_combos.length > 0}
                <WeaponsPopover
                  combos={entry.weapon_combos}
                  minPercent={1}
                  title="{entry.user.twitch_display_name ??
                    entry.user.twitch_username}'s weekly loadout"
                />
              {/if}
            </div>
          </div>
        </li>
      {/each}
    </ol>
  {/if}
</div>

<style>
  .week-leaderboard {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .list {
    list-style: none;
    margin: 0;
    /* Right padding keeps row content off the scrollbar. */
    padding: 0 0.4rem 0 0;
    flex: 1;
    overflow-y: auto;
  }

  .row {
    display: grid;
    grid-template-columns: 1.5rem 1fr auto;
    column-gap: 0.4rem;
    align-items: center;
    padding: 0.35rem 0;
    border-bottom: 1px solid var(--color-border);
  }

  .row.me {
    background: rgba(139, 92, 246, 0.1);
    border-radius: var(--radius-sm);
  }

  .rank {
    color: var(--color-text-secondary);
    font-variant-numeric: tabular-nums;
    font-weight: 600;
    text-align: right;
    padding-right: 0.25rem;
  }

  .rank-gold {
    color: var(--color-gold);
  }

  .rank-silver {
    color: #b8c5d6;
  }

  .rank-bronze {
    color: #d4a574;
  }

  .middle {
    min-width: 0;
  }

  .name-line {
    display: flex;
    align-items: center;
    gap: 0.3rem;
  }

  .sub-left {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs, 11px);
    font-variant-numeric: tabular-nums;
    margin-top: 1px;
  }

  .right {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .points {
    color: var(--color-success);
    font-weight: 600;
    font-size: var(--font-size-sm);
  }

  .sub-right {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 0.4rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs, 11px);
    margin-top: 1px;
  }

  .deaths::before {
    content: "💀 ";
  }

  .empty {
    color: var(--color-text-secondary);
    text-align: center;
    padding: 1rem 0.5rem;
  }
</style>
