<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import type { WeaponCombo } from "$lib/zone-history";
  import { topCombos, formatCombo } from "$lib/weapons";
  import {
    getWeaponName,
    loadCatalogue,
  } from "$lib/stores/weaponsCatalogue.svelte";

  interface Props {
    combos: WeaponCombo[];
    maxRows?: number;
    title?: string;
    showPercent?: boolean;
  }

  let { combos, maxRows = 3, title, showPercent = true }: Props = $props();

  let open = $state(false);
  let triggerEl: HTMLSpanElement | undefined = $state();
  let popupEl: HTMLDivElement | undefined = $state();
  let popupTop = $state(0);
  let popupLeft = $state(0);

  const POPUP_WIDTH = 200;

  const rows = $derived(topCombos(combos, maxRows));

  function recomputePosition() {
    if (!triggerEl) return;
    const rect = triggerEl.getBoundingClientRect();
    let top = rect.bottom + 4;
    let left = rect.left;
    if (left + POPUP_WIDTH > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - POPUP_WIDTH - 8);
    }
    popupTop = top;
    popupLeft = left;
  }

  function openPopup() {
    recomputePosition();
    open = true;
  }
  function closePopup() {
    open = false;
  }
  function handleClickOutside(e: MouseEvent) {
    if (!open) return;
    if (
      popupEl &&
      !popupEl.contains(e.target as Node) &&
      triggerEl &&
      !triggerEl.contains(e.target as Node)
    ) {
      closePopup();
    }
  }
  function handleKey(e: KeyboardEvent) {
    if (e.key === "Escape") closePopup();
  }
  function handleScrollOrResize() {
    if (open) closePopup();
  }

  onMount(() => {
    loadCatalogue();
    document.addEventListener("click", handleClickOutside);
    document.addEventListener("keydown", handleKey);
    window.addEventListener("scroll", handleScrollOrResize, { capture: true });
    window.addEventListener("resize", handleScrollOrResize);
  });
  onDestroy(() => {
    document.removeEventListener("click", handleClickOutside);
    document.removeEventListener("keydown", handleKey);
    window.removeEventListener("scroll", handleScrollOrResize, {
      capture: true,
    });
    window.removeEventListener("resize", handleScrollOrResize);
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span class="popover-anchor" onmouseenter={openPopup} onmouseleave={closePopup}>
  <span
    bind:this={triggerEl}
    class="trigger"
    role="button"
    tabindex="0"
    aria-label={title ?? "Weapons"}
    onclick={(e) => {
      e.stopPropagation();
      if (!open) {
        recomputePosition();
      }
      open = !open;
    }}
    onkeydown={(e) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        if (!open) {
          recomputePosition();
        }
        open = !open;
      }
    }}
  >
    ⚔
  </span>

  {#if open && rows.length > 0}
    <div
      bind:this={popupEl}
      class="popup"
      role="dialog"
      aria-label={title ?? "Weapons"}
      style="top: {popupTop}px; left: {popupLeft}px;"
    >
      {#if title}
        <div class="popup-title">{title}</div>
      {/if}
      <ul class="combo-list">
        {#each rows as row}
          <li>
            <span class="combo-name">{formatCombo(row.ids, getWeaponName)}</span
            >
            {#if showPercent}
              <span class="combo-percent">{row.percent}%</span>
            {/if}
          </li>
        {/each}
      </ul>
    </div>
  {/if}
</span>

<style>
  .popover-anchor {
    display: inline-block;
  }
  .trigger {
    cursor: pointer;
    user-select: none;
    font-size: 0.9em;
    opacity: 0.75;
  }
  .trigger:hover {
    opacity: 1;
  }
  .popup {
    position: fixed;
    z-index: 200;
    background: var(--color-bg-elevated, #1f1f2e);
    border: 1px solid var(--color-border, #333);
    border-radius: var(--radius-sm, 4px);
    padding: 0.5rem 0.75rem;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.35);
    min-width: 180px;
    font-size: var(--font-size-sm, 0.85rem);
  }
  .popup-title {
    font-weight: 600;
    margin-bottom: 0.35rem;
    color: var(--color-text-secondary, #aaa);
  }
  .combo-list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.2rem;
  }
  .combo-list li {
    display: flex;
    justify-content: space-between;
    gap: 0.75rem;
  }
  .combo-percent {
    color: var(--color-text-secondary, #888);
    font-variant-numeric: tabular-nums;
  }
</style>
