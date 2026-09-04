<script lang="ts">
  import { onMount } from "svelte";
  import EmphasisText from "$lib/components/EmphasisText.svelte";
  import { CONTENT_ITEMS } from "$lib/content/items";
  import {
    isExperiencedPlayer,
    loadSeenTipIds,
    markTipSeen,
    orderTickerItems,
  } from "$lib/content/select";
  import type { ContentItem } from "$lib/content/types";
  import { auth } from "$lib/stores/auth.svelte";

  interface Props {
    poolName?: string | null;
    variant?: "panel" | "banner";
  }

  let { poolName = null, variant = "panel" }: Props = $props();

  const ROTATE_MS = 15_000;

  let items = $state<ContentItem[]>([]);
  let index = $state(0);
  let paused = $state(false);
  let timer: ReturnType<typeof setInterval> | undefined;

  const current = $derived(items[index]);

  function storage(): Storage | null {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  }

  function show(next: number) {
    index = next;
    markTipSeen(storage(), items[index].id);
  }

  function schedule() {
    clearInterval(timer);
    timer = setInterval(() => {
      if (paused || items.length < 2) return;
      show((index + 1) % items.length);
    }, ROTATE_MS);
  }

  function step(delta: number) {
    if (items.length < 2) return;
    show((index + delta + items.length) % items.length);
    // Restart the period so a tip picked by hand stays up as long as an
    // automatic one would.
    schedule();
  }

  onMount(() => {
    items = orderTickerItems(CONTENT_ITEMS, {
      poolName,
      seenIds: loadSeenTipIds(storage()),
      experienced: isExperiencedPlayer(auth.user),
    });
    if (items.length > 0) markTipSeen(storage(), items[0].id);
    schedule();
    return () => clearInterval(timer);
  });
</script>

{#if current}
  <aside
    class="tip-ticker"
    class:banner={variant === "banner"}
    onmouseenter={() => (paused = true)}
    onmouseleave={() => (paused = false)}
  >
    <div class="ticker-head">
      <span class="ticker-label">
        {variant === "panel" ? "While you wait" : "Tip"}
      </span>
      <span class="ticker-nav">
        <span class="ticker-count">{index + 1}/{items.length}</span>
        <button
          type="button"
          class="nav-btn"
          data-tip-nav="prev"
          aria-label="Previous tip"
          disabled={items.length < 2}
          onclick={() => step(-1)}
        >
          <span aria-hidden="true">&larr;</span>
        </button>
        <button
          type="button"
          class="nav-btn"
          data-tip-nav="next"
          aria-label="Next tip"
          disabled={items.length < 2}
          onclick={() => step(1)}
        >
          <span aria-hidden="true">&rarr;</span>
        </button>
      </span>
    </div>
    <div class="tip-content">
      <span class="tip-title">{current.title}</span>
      <p class="tip-text"><EmphasisText text={current.short} /></p>
    </div>
    <a
      class="ticker-more"
      href="/game-changes"
      target="_blank"
      rel="noopener noreferrer">Game changes</a
    >
  </aside>
{/if}

<style>
  .tip-ticker {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    height: 100%;
    background: var(--color-surface-elevated);
    border-left: 1px solid var(--color-border);
    border-radius: 0 var(--radius-md) var(--radius-md) 0;
    padding: 0.9rem 1rem;
    overflow-y: auto;
  }

  .ticker-head {
    display: flex;
    justify-content: space-between;
    align-items: center;
    border-bottom: 1px solid var(--color-border);
    padding-bottom: 0.4rem;
  }

  .ticker-nav {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
  }

  .ticker-label {
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--color-text-secondary);
  }

  .ticker-count {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-disabled, #6b7280);
    margin-right: 0.2rem;
  }

  .nav-btn {
    appearance: none;
    background: transparent;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text-secondary);
    width: 1.5rem;
    height: 1.5rem;
    padding: 0;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    line-height: 1;
    transition:
      color var(--transition),
      border-color var(--transition);
  }

  .nav-btn:hover:not(:disabled) {
    color: var(--color-purple);
    border-color: var(--color-purple);
  }

  .nav-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }

  .tip-title {
    display: block;
    color: var(--color-gold);
    font-weight: 600;
    font-size: var(--font-size-sm);
    margin-bottom: 0.2rem;
  }

  .tip-text {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    line-height: 1.5;
  }

  .ticker-more {
    margin-top: auto;
    font-size: var(--font-size-xs);
    align-self: flex-end;
  }

  /* Banner variant: one horizontal strip, no fill-height behavior. */
  .tip-ticker.banner {
    flex-direction: row;
    align-items: baseline;
    gap: 0.8rem;
    height: auto;
    overflow: visible;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }

  .tip-ticker.banner .ticker-head {
    border-bottom: none;
    padding-bottom: 0;
    flex-shrink: 0;
    gap: 0.5rem;
    display: flex;
  }

  .tip-ticker.banner .tip-content {
    min-width: 0;
    /* Reserve two line boxes so rotating between short (1-line) and long
       (2-line) tips doesn't shift the layout below the banner. */
    min-height: 2lh;
  }

  .tip-ticker.banner .tip-title {
    display: inline;
    margin-right: 0.4rem;
  }

  .tip-ticker.banner .tip-text {
    display: inline;
  }

  .tip-ticker.banner .ticker-more {
    margin-top: 0;
    margin-left: auto;
    align-self: flex-start;
    flex-shrink: 0;
  }
</style>
