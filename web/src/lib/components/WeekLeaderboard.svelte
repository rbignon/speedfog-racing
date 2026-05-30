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
          <span class="rank-circle r-{Math.min(entry.rank, 3)}"
            >{entry.rank}</span
          >
          <div class="middle">
            <div class="name-line">
              <!-- WeeklyLeaderboardUser is structurally identical to User -->
              <UserLink
                user={entry.user as import("$lib/api").User}
                showBadge
              />
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
    display: flex;
    flex-direction: column;
  }

  .list {
    list-style: none;
    padding: 0;
    margin: 0;
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

  .rank-circle {
    width: 1.5rem;
    height: 1.5rem;
    border-radius: 50%;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    font-variant-numeric: tabular-nums;
  }

  .rank-circle.r-1 {
    background: rgba(200, 164, 78, 0.18);
    border-color: var(--color-gold);
    color: var(--color-gold);
  }

  .rank-circle.r-2 {
    background: rgba(184, 197, 214, 0.15);
    border-color: #b8c5d6;
    color: #b8c5d6;
  }

  .rank-circle.r-3 {
    background: rgba(212, 165, 116, 0.15);
    border-color: #d4a574;
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
    color: var(--color-gold);
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
