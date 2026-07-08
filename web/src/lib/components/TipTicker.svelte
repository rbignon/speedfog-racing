<script lang="ts">
  import { onMount } from "svelte";
  import { CONTENT_ITEMS } from "$lib/content/items";
  import {
    loadSeenTipIds,
    markTipSeen,
    orderTickerItems,
  } from "$lib/content/select";
  import type { ContentItem } from "$lib/content/types";

  interface Props {
    poolName?: string | null;
    variant?: "panel" | "banner";
  }

  let { poolName = null, variant = "panel" }: Props = $props();

  const ROTATE_MS = 15_000;

  let items = $state<ContentItem[]>([]);
  let index = $state(0);
  let paused = $state(false);

  const current = $derived(items[index]);

  function storage(): Storage | null {
    try {
      return window.localStorage;
    } catch {
      return null;
    }
  }

  onMount(() => {
    items = orderTickerItems(CONTENT_ITEMS, {
      poolName,
      seenIds: loadSeenTipIds(storage()),
    });
    if (items.length > 0) markTipSeen(storage(), items[0].id);
    const timer = setInterval(() => {
      if (paused || items.length < 2) return;
      index = (index + 1) % items.length;
      markTipSeen(storage(), items[index].id);
    }, ROTATE_MS);
    return () => clearInterval(timer);
  });
</script>

{#if current}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
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
      <span class="ticker-count">{index + 1}/{items.length}</span>
    </div>
    <div class="tip-content">
      <span class="tip-title">{current.title}</span>
      <p class="tip-text">{current.short}</p>
    </div>
    <a class="ticker-more" href="/game-changes">Game changes &rarr;</a>
  </aside>
{/if}

<style>
  .tip-ticker {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    height: 100%;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 0.9rem 1rem;
    overflow-y: auto;
  }

  .ticker-head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    border-bottom: 1px solid var(--color-border);
    padding-bottom: 0.4rem;
  }

  .ticker-label {
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    letter-spacing: 0.08em;
    color: var(--color-text-secondary);
  }

  .ticker-count {
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: var(--font-size-xs);
    color: var(--color-text-disabled, #6b7280);
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
    align-self: flex-start;
  }

  /* Banner variant: one horizontal strip, no fill-height behavior. */
  .tip-ticker.banner {
    flex-direction: row;
    align-items: baseline;
    gap: 0.8rem;
    height: auto;
    overflow: visible;
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
    flex-shrink: 0;
  }
</style>
