<script lang="ts">
  import { onMount, onDestroy } from "svelte";
  import { portal } from "$lib/utils/portal";

  let {
    rules,
    align = "left",
  }: { rules: string | null; align?: "left" | "right" } = $props();

  const ruleLines = $derived(
    (rules ?? "")
      .split("\n")
      .map((line) => line.trim())
      .filter((line) => line.length > 0),
  );

  let open = $state(false);
  let triggerEl: HTMLSpanElement | undefined = $state();
  let popupEl: HTMLDivElement | undefined = $state();
  let popupTop = $state(0);
  let popupLeft = $state(0);
  let popupRight: number | null = $state(null);
  let triggerHovered = false;
  let popupHovered = false;
  let closeTimer: ReturnType<typeof setTimeout> | undefined;

  const POPUP_WIDTH = 300;
  const HOVER_CLOSE_DELAY_MS = 80;

  function recomputePosition() {
    if (!triggerEl) return;
    const rect = triggerEl.getBoundingClientRect();
    popupTop = rect.bottom + 4;
    if (align === "right") {
      // Anchor the popup's right edge under the trigger so it expands leftward.
      popupRight = Math.max(8, window.innerWidth - rect.right);
      return;
    }
    let left = rect.left;
    if (left + POPUP_WIDTH > window.innerWidth - 8) {
      left = Math.max(8, window.innerWidth - POPUP_WIDTH - 8);
    }
    popupLeft = left;
  }

  function cancelClose() {
    if (closeTimer !== undefined) {
      clearTimeout(closeTimer);
      closeTimer = undefined;
    }
  }
  function openPopup() {
    cancelClose();
    recomputePosition();
    open = true;
  }
  function closePopup() {
    cancelClose();
    open = false;
  }
  // Portaled popup is no longer a DOM descendant of the anchor, so we need a
  // short grace period when leaving either side to let the cursor cross the
  // gap without the popup closing under it.
  function queueClose() {
    cancelClose();
    closeTimer = setTimeout(() => {
      closeTimer = undefined;
      if (!triggerHovered && !popupHovered) open = false;
    }, HOVER_CLOSE_DELAY_MS);
  }
  function onTriggerEnter() {
    triggerHovered = true;
    openPopup();
  }
  function onTriggerLeave() {
    triggerHovered = false;
    queueClose();
  }
  function onPopupEnter() {
    popupHovered = true;
    cancelClose();
  }
  function onPopupLeave() {
    popupHovered = false;
    queueClose();
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
    cancelClose();
  });
</script>

{#if ruleLines.length > 0}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <span
    class="popover-anchor"
    onmouseenter={onTriggerEnter}
    onmouseleave={onTriggerLeave}
  >
    <span
      bind:this={triggerEl}
      class="trigger"
      role="button"
      tabindex="0"
      aria-label="Mode rules"
      aria-haspopup="dialog"
      aria-expanded={open}
      onclick={(e) => {
        e.stopPropagation();
        if (open) closePopup();
        else openPopup();
      }}
      onkeydown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          if (open) closePopup();
          else openPopup();
        }
      }}
    >
      <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
        <path
          d="M2 4h12M2 8h12M2 12h8"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          fill="none"
        />
      </svg>
      Mode Rules
    </span>

    {#if open}
      <div
        bind:this={popupEl}
        use:portal
        class="popup"
        role="dialog"
        tabindex="-1"
        aria-label="Mode rules"
        style="top: {popupTop}px; {popupRight !== null
          ? `right: ${popupRight}px;`
          : `left: ${popupLeft}px;`}"
        onmouseenter={onPopupEnter}
        onmouseleave={onPopupLeave}
      >
        <ul class="rules-list">
          {#each ruleLines as line}
            <li>{line}</li>
          {/each}
        </ul>
      </div>
    {/if}
  </span>
{/if}

<style>
  .popover-anchor {
    display: inline-block;
    flex-shrink: 0;
  }
  .trigger {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    white-space: nowrap;
    cursor: pointer;
    user-select: none;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    transition: color var(--transition);
  }
  .trigger:hover,
  .trigger:focus-visible {
    color: var(--color-gold);
  }
  .trigger svg {
    flex-shrink: 0;
  }
  .popup {
    position: fixed;
    z-index: 200;
    max-width: 300px;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-left: 3px solid var(--color-gold);
    border-radius: var(--radius-sm);
    padding: 0.6rem 0.85rem;
    box-shadow: 0 6px 16px rgba(0, 0, 0, 0.35);
    font-size: var(--font-size-sm);
  }
  .rules-list {
    list-style: disc;
    margin: 0;
    padding-left: 1.1rem;
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    color: var(--color-text-secondary);
  }
</style>
