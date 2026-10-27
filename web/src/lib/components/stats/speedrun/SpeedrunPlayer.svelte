<script lang="ts">
  import type { User } from "$lib/api";
  import UserLink from "$lib/components/UserLink.svelte";
  import { rewards } from "$lib/stores/rewards.svelte";

  let { user, raceName }: { user: User; raceName?: string } = $props();

  // The equipped badge stands where speedrun.com shows a country flag.
  let badge = $derived(rewards.lookupBadge(user.equipped_badge_id ?? null));
</script>

<span class="sr-player">
  {#if badge}
    <img
      class="flag"
      src="/badges/{badge.icon_filename}"
      alt={badge.name}
      title={badge.name}
    />
  {:else}
    <span class="flag" aria-hidden="true"></span>
  {/if}
  <span class="name"><UserLink {user} /></span>
  {#if raceName}
    <span class="bubble" title={raceName} aria-label="Race: {raceName}">
      <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
        <path
          d="M4 5h16v11H9l-5 4V5Z"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        />
      </svg>
    </span>
  {/if}
</span>

<style>
  .sr-player {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
  }

  .flag {
    width: 16px;
    height: 16px;
    flex-shrink: 0;
  }

  .name {
    display: inline-flex;
    min-width: 0;
    font-weight: 700;
  }

  .bubble {
    display: inline-flex;
    margin-left: auto;
    padding-left: 0.5rem;
    color: var(--color-text-secondary);
    cursor: help;
  }
</style>
