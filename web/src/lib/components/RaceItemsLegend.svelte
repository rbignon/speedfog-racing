<script lang="ts">
  import {
    RACE_ITEMS,
    raceItemTierLine,
    type RaceItemInfo,
  } from "$lib/raceItems";

  // The last item pointed at stays described: leaving the strip must not
  // blank the line a reader is still on, and a tap has no "leave".
  // Raw: a proxied copy would never equal the catalog's own object.
  let active = $state.raw<RaceItemInfo | null>(null);
</script>

<div class="items-legend">
  <div class="items-strip">
    {#each RACE_ITEMS as item (item.key)}
      <button
        type="button"
        class="item-btn"
        class:active={active === item}
        aria-label={item.name}
        onmouseenter={() => (active = item)}
        onfocus={() => (active = item)}
        onclick={() => (active = item)}
      >
        <img
          src="/race_items/{item.key}.png"
          alt=""
          width="32"
          height="32"
          loading="lazy"
        />
      </button>
    {/each}
  </div>
  <p class="item-detail" aria-live="polite">
    {#if active}
      <strong>{active.name}:</strong>
      {active.effect}
      <span class="item-tiers">{raceItemTierLine(active.tiers)}</span>
    {:else}
      <span class="item-tiers"
        >Hover, focus or tap an item to see what it does.</span
      >
    {/if}
  </p>
</div>

<style>
  .items-legend {
    margin-top: 0.5rem;
  }
  .items-strip {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
  }
  .item-btn {
    display: flex;
    padding: 0.2rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    cursor: help;
    transition: border-color 0.12s;
  }
  .item-btn.active {
    border-color: var(--color-gold);
  }
  .item-btn:focus-visible {
    outline: 2px solid var(--color-gold);
    outline-offset: 1px;
  }
  .item-btn img {
    display: block;
    width: 32px;
    height: 32px;
  }
  .item-detail {
    margin: 0.4rem 0 0;
    /* Reserved (the effect, then the tiers), so the card keeps its height. */
    min-height: 3em;
    line-height: 1.5;
  }
  .item-detail strong {
    color: var(--color-gold);
    font-weight: 600;
  }
  .item-tiers {
    display: block;
    color: var(--color-text-disabled);
  }
  @media (max-width: 768px) {
    .item-detail {
      min-height: 6em;
    }
  }
</style>
