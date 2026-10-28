<script lang="ts">
  import { untrack } from "svelte";
  import type { SpeedrunRunType } from "$lib/api";
  import { auth } from "$lib/stores/auth.svelte";
  import {
    SPEEDRUN_OVERLAY_DEFAULTS as DEFAULTS,
    speedrunOverlayUrl,
    type SpeedrunSub,
  } from "$lib/speedrun";
  import { copyToClipboard } from "$lib/utils/clipboard";

  interface Props {
    pool: string;
    categoryName: string;
    sub: SpeedrunSub;
    types: SpeedrunRunType[];
    onClose: () => void;
  }

  let { pool, categoryName, sub, types, onClose }: Props = $props();

  let top = $state<number | null>(DEFAULTS.top);
  let cycle = $state<number | null>(DEFAULTS.cycle);
  let until = $state<number | null>(DEFAULTS.until);
  let player = $state(untrack(() => auth.user?.twitch_username ?? ""));
  let copied = $state(false);

  // An emptied number field falls back to its default.
  function count(value: number | null, fallback: number): number {
    return value === null || !Number.isFinite(value)
      ? fallback
      : Math.max(0, Math.floor(value));
  }

  let url = $derived(
    speedrunOverlayUrl(window.location.origin, pool, {
      sub,
      types,
      top: count(top, DEFAULTS.top),
      cycle: count(cycle, DEFAULTS.cycle),
      until: count(until, DEFAULTS.until),
      player: player.trim() || null,
    }),
  );

  async function copyUrl() {
    if (!(await copyToClipboard(url))) return;
    copied = true;
    setTimeout(() => (copied = false), 2000);
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="modal-backdrop"
  onclick={onClose}
  onkeydown={(e) => e.key === "Escape" && onClose()}
>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="modal" onclick={(e) => e.stopPropagation()}>
    <div class="modal-header">
      <h2>OBS Overlay</h2>
      <button class="close-btn" onclick={onClose}>&times;</button>
    </div>

    <p class="description">
      Add it as a <strong>Browser Source</strong> in OBS with a transparent
      background. It shows the {categoryName}
      {sub === "deathless" ? "Deathless" : "Any%"} leaderboard (personal bests only)
      for the run types currently selected.
    </p>
    <p class="size-hint">Recommended size: 400 &times; 300</p>

    <div class="config-row">
      <label for="sr-top">Fixed rows</label>
      <input
        id="sr-top"
        type="number"
        min="0"
        max="20"
        bind:value={top}
        class="config-input"
      />
    </div>
    <p class="config-hint">Always shown, from first place.</p>
    <div class="config-row">
      <label for="sr-cycle">Cycling rows</label>
      <input
        id="sr-cycle"
        type="number"
        min="0"
        max="10"
        bind:value={cycle}
        class="config-input"
      />
    </div>
    <div class="config-row">
      <label for="sr-until">Cycle up to rank</label>
      <input
        id="sr-until"
        type="number"
        min="1"
        bind:value={until}
        class="config-input"
      />
    </div>
    <p class="config-hint">
      The players after the fixed rows, a page at a time.
    </p>
    <div class="config-row">
      <label for="sr-player">Pinned player</label>
      <input
        id="sr-player"
        type="text"
        placeholder="Twitch username"
        bind:value={player}
        class="config-input player-input"
      />
    </div>
    <p class="config-hint">
      Their personal best stays at the bottom. Leave empty for none.
    </p>

    <div class="url-row">
      <input type="text" readonly value={url} class="url-input" />
      <button class="btn btn-primary copy-btn" onclick={copyUrl}>
        {copied ? "Copied!" : "Copy"}
      </button>
    </div>
  </div>
</div>

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
    max-width: 500px;
    width: 90%;
    max-height: calc(100dvh - 2rem);
    overflow-y: auto;
    overscroll-behavior: contain;
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
  }

  .modal-header h2 {
    margin: 0;
    color: var(--color-gold);
    font-size: var(--font-size-lg);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--color-text-secondary);
    font-size: 1.5rem;
    cursor: pointer;
    padding: 0;
    line-height: 1;
  }

  .close-btn:hover {
    color: var(--color-text);
  }

  .description {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    margin: 0 0 0.25rem 0;
  }

  .size-hint {
    margin: 0 0 1rem 0;
    font-size: var(--font-size-sm);
    color: var(--color-text-disabled);
  }

  .config-row {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .config-row label {
    min-width: 8.5rem;
  }

  .config-input {
    width: 5rem;
    padding: 0.25rem 0.5rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
  }

  .player-input {
    flex: 1;
    min-width: 0;
    max-width: 14rem;
  }

  .config-hint {
    margin: -0.25rem 0 0.75rem 0;
    font-size: var(--font-size-xs, 0.75rem);
    color: var(--color-text-disabled);
  }

  .url-row {
    display: flex;
    gap: 0.5rem;
    margin-top: 1rem;
  }

  .url-input {
    flex: 1;
    padding: 0.5rem 0.75rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    min-width: 0;
  }

  .copy-btn {
    font-size: var(--font-size-sm);
  }
</style>
