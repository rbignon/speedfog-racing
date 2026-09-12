<script lang="ts">
  import { onMount } from "svelte";
  import { auth } from "$lib/stores/auth.svelte";
  import {
    fetchTrainingPools,
    getTwitchLoginUrl,
    type EventMode,
    type PoolStats,
  } from "$lib/api";
  import { soloPoolName, soloPoolPath, soloSeedLabel } from "$lib/events";

  let { modes }: { modes: EventMode[] } = $props();

  let signedIn = $derived(auth.isLoggedIn);

  // Seed counts come from the public pools endpoint, which answers a
  // signed-out viewer too (without their played count). A failure leaves the
  // cards saying what they are, which is the part that matters.
  let pools: PoolStats = $state({});

  onMount(async () => {
    try {
      pools = await fetchTrainingPools();
    } catch {
      /* the cards stand without their counts */
    }
  });

  // Signed out the card leads to Twitch, and comes back to the solo page on
  // the mode it named rather than to this one: the click keeps its intent.
  function rememberMode(key: string) {
    sessionStorage.setItem("redirect_after_login", soloPoolPath(key));
  }
</script>

<div class="cards">
  {#each modes as mode (mode.key)}
    <a
      class="practice-card"
      href={signedIn ? soloPoolPath(mode.key) : getTwitchLoginUrl()}
      data-sveltekit-reload={signedIn ? undefined : true}
      onclick={signedIn ? undefined : () => rememberMode(mode.key)}
      aria-label={signedIn
        ? `Practice ${mode.label} solo`
        : `Sign in to practice ${mode.label} solo`}
    >
      <span class="name">{mode.label}</span>
      <span class="meta">{soloSeedLabel(pools[soloPoolName(mode.key)])}</span>
    </a>
  {/each}
</div>

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
  .meta {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }
</style>
