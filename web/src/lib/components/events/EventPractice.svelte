<script lang="ts">
  import { auth } from "$lib/stores/auth.svelte";
  import type { EventMode } from "$lib/api";
  import { soloPoolPath } from "$lib/events";

  let { modes }: { modes: EventMode[] } = $props();
</script>

{#if auth.user}
  <div class="cards">
    {#each modes as mode (mode.key)}
      <a
        class="practice-card"
        href={soloPoolPath(mode.key)}
        aria-label="Practice {mode.label} solo"
      >
        <span class="name">{mode.label}</span>
        <span class="meta">Solo seeds</span>
      </a>
    {/each}
  </div>
{:else}
  <!-- Signed out, every card would lead to the same Twitch page: three names
       for one action. The modes are named instead, and the sign-in stays
       where it already is, a step above. -->
  <p class="modes">
    {#each modes as mode (mode.key)}<span class="chip">{mode.label}</span
      >{/each}<span class="meta">Sign in to run one</span>
  </p>
{/if}

<style>
  .cards {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
    gap: 14px;
  }
  .practice-card {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 0.9rem 1rem;
    color: inherit;
    text-decoration: none;
    transition: border-color var(--transition);
  }
  .practice-card:hover {
    border-color: var(--color-purple);
  }
  .name {
    font-family: var(--font-display);
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }
  .modes {
    margin: 0;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
  }
  .meta {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }
</style>
