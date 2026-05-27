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
  }

  let { combos, maxRows = 3, title }: Props = $props();

  let open = $state(false);
  let triggerEl: HTMLSpanElement | undefined = $state();
  let popupEl: HTMLDivElement | undefined = $state();

  const rows = $derived(topCombos(combos, maxRows));

  function openPopup() {
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

  onMount(() => {
    loadCatalogue();
    document.addEventListener("click", handleClickOutside);
    document.addEventListener("keydown", handleKey);
  });
  onDestroy(() => {
    document.removeEventListener("click", handleClickOutside);
    document.removeEventListener("keydown", handleKey);
  });
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<span
  bind:this={triggerEl}
  class="trigger"
  role="button"
  tabindex="0"
  aria-label={title ?? "Weapons"}
  onmouseenter={openPopup}
  onmouseleave={closePopup}
  onclick={(e) => {
    e.stopPropagation();
    open = !open;
  }}
  onkeydown={(e) => {
    if (e.key === "Enter" || e.key === " ") {
      e.preventDefault();
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
  >
    {#if title}
      <div class="popup-title">{title}</div>
    {/if}
    <ul class="combo-list">
      {#each rows as row}
        <li>
          <span class="combo-name">{formatCombo(row.ids, getWeaponName)}</span>
          <span class="combo-percent">{row.percent}%</span>
        </li>
      {/each}
    </ul>
  </div>
{/if}

<style>
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
    position: absolute;
    z-index: 50;
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
