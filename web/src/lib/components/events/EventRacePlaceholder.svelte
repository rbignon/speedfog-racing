<script lang="ts">
  import type { User } from "$lib/api";

  /**
   * A stage race slot nothing is attached to yet: the race card's geometry
   * (route line as the top edge) with the setup dashes, no link, and the
   * runners expected on the evening as an avatar stack.
   */
  let { name, users }: { name: string; users: User[] } = $props();
</script>

<div class="card">
  <div class="route route-setup" aria-hidden="true">
    <span class="line"></span>
    <span class="m-start"></span>
    <span class="m-end"></span>
  </div>
  <div class="head">
    <span class="name">{name}</span>
    <span class="signal signal-setup">Upcoming</span>
  </div>
  {#if users.length > 0}
    <div class="avatar-stack">
      {#each users as user, i (i)}
        {#if user.twitch_avatar_url}
          <img
            src={user.twitch_avatar_url}
            alt={user.twitch_display_name || user.twitch_username}
            title={user.twitch_display_name || user.twitch_username}
            class="avatar"
          />
        {:else}
          <span
            class="avatar avatar-placeholder"
            title={user.twitch_display_name || user.twitch_username}
          >
            {(user.twitch_display_name || user.twitch_username)
              .charAt(0)
              .toUpperCase()}
          </span>
        {/if}
      {/each}
    </div>
  {/if}
</div>

<style>
  .card {
    position: relative;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    padding: 0.8rem 1.1rem 0.9rem;
    min-width: 0;
  }
  .card > :global(.route) {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.75rem;
  }
  .name {
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  @media (max-width: 640px) {
    .name {
      white-space: normal;
      overflow: visible;
    }
  }
  .avatar-stack {
    display: flex;
    align-items: center;
    margin-top: 0.75rem;
  }
  .avatar {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    border: 2px solid var(--color-surface);
    margin-left: -6px;
    object-fit: cover;
  }
  .avatar:first-child {
    margin-left: 0;
  }
  .avatar-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface-elevated);
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }
</style>
