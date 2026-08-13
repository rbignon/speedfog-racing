<script lang="ts">
  import type { NodePopupData } from "./popupData";
  import { formatIgt } from "./popupData";
  import { formatGapCompact } from "$lib/gap";
  import { NODE_COLORS } from "./constants";
  import WeaponsPopover from "$lib/components/WeaponsPopover.svelte";
  import SkullIcon from "$lib/components/SkullIcon.svelte";
  import { skipCountForZones } from "$lib/content/zones";

  interface Props {
    data: NodePopupData;
    x: number;
    y: number;
    onclose: () => void;
    onzonecodex?: (
      nodeId: string,
      displayName: string,
      zones: string[],
    ) => void;
  }

  let { data, x, y, onclose, onzonecodex }: Props = $props();

  // Type label mapping
  const TYPE_LABELS: Record<string, string> = {
    start: "Starting Area",
    final_boss: "Final Boss",
    legacy_dungeon: "Legacy Dungeon",
    major_boss: "Major Boss",
    boss_arena: "Boss Arena",
    mini_dungeon: "Mini Dungeon",
  };

  let popupEl: HTMLDivElement | undefined = $state();

  // Clamp position to viewport after mount (initialized by $effect below)
  let adjustedX = $state(0);
  let adjustedY = $state(0);

  $effect(() => {
    if (!popupEl) return;
    const rect = popupEl.getBoundingClientRect();
    const pad = 12;
    let nx = x + 16; // offset right of click
    let ny = y - 8; // slightly above click

    // Clamp right edge
    if (nx + rect.width > window.innerWidth - pad) {
      nx = x - rect.width - 16; // flip to left
    }
    // Clamp bottom edge
    if (ny + rect.height > window.innerHeight - pad) {
      ny = window.innerHeight - rect.height - pad;
    }
    // Clamp top edge
    if (ny < pad) {
      ny = pad;
    }
    // Clamp left edge
    if (nx < pad) {
      nx = pad;
    }

    adjustedX = nx;
    adjustedY = ny;
  });

  // Close on pointerdown outside (not click, to avoid race with onnodeclick which fires on pointerup)
  function onWindowPointerDown(e: PointerEvent) {
    if (popupEl && !popupEl.contains(e.target as Node)) {
      onclose();
    }
  }

  let typeColor = $derived(NODE_COLORS[data.type] ?? "#999");
</script>

<svelte:window onpointerdown={onWindowPointerDown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  bind:this={popupEl}
  class="node-popup"
  style="left: {adjustedX}px; top: {adjustedY}px;"
  onpointerdown={(e) => e.stopPropagation()}
>
  <!-- Header -->
  <div class="popup-header">
    <div class="popup-title">
      <span class="popup-name">{data.displayName}</span>
      <button class="popup-close" onclick={onclose}>&times;</button>
    </div>
    <div class="popup-meta">
      <span class="type-badge" style="color: {typeColor};"
        >{data.displayType ?? TYPE_LABELS[data.type] ?? data.type}</span
      >
      {#if data.tier > 0}
        <span class="tier-badge">Tier {data.tier}</span>
      {/if}
      <span class="layer-badge">Depth {data.layer + 1}</span>
    </div>
    {#if data.randomizedBosses?.length}
      <div class="popup-boss">
        <span class="boss-label">Boss:</span>
        {data.randomizedBosses.join(", ")}
      </div>
    {/if}
  </div>

  <!-- Connections -->
  {#if data.entrances.length > 0}
    <div class="popup-section">
      <div class="section-title">Entrances</div>
      {#each data.entrances as conn}
        <div class="conn-item">
          <span class="conn-arrow entrance">&larr;</span>
          <div class="conn-details">
            <span class="conn-name" class:undiscovered={!conn.displayName}>
              {conn.displayName ?? "???"}
            </span>
            {#if conn.text}
              <span class="conn-text">To: {conn.text}</span>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}

  {#if data.exits.length > 0}
    <div class="popup-section">
      <div class="section-title">Exits</div>
      {#each data.exits as conn}
        <div class="conn-item">
          <span class="conn-arrow exit">&rarr;</span>
          <div class="conn-details">
            <span class="conn-name" class:undiscovered={!conn.displayName}>
              {conn.displayName ?? "???"}
            </span>
            {#if conn.text}
              <span class="conn-text">From: {conn.text}</span>
            {/if}
          </div>
        </div>
      {/each}
    </div>
  {/if}

  <!-- Players at this node (live/results) -->
  {#if data.playersHere && data.playersHere.length > 0}
    <div class="popup-section">
      <div class="section-title">Players here</div>
      <div class="player-list">
        {#each data.playersHere as player}
          <span class="player-chip">
            <span class="player-dot" style="background: {player.color};"></span>
            {player.displayName}
          </span>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Visitors (results only) -->
  {#if data.visitors && data.visitors.length > 0}
    <!-- Delta reference: the first row, i.e. the fastest cleared visitor.
         Only cleared rows show a gap: backed/playing/abandoned visitors did
         not complete the zone, so comparing their time spent is meaningless. -->
    {@const refTimeMs = data.visitors[0].timeSpentMs}
    <div class="popup-section">
      <div class="section-title">Visited by</div>
      <div class="visitor-grid">
        {#each data.visitors as visitor, i}
          {@const gapMs =
            i > 0 &&
            visitor.outcome === "cleared" &&
            refTimeMs != null &&
            visitor.timeSpentMs != null
              ? visitor.timeSpentMs - refTimeMs
              : null}
          <div class="visitor-row" class:me={visitor.isMe}>
            <span class="player-dot" style="background: {visitor.color};"
            ></span>
            <span
              class="visitor-name"
              class:visitor-backed={visitor.outcome === "backed"}
              class:visitor-abandoned={visitor.outcome === "abandoned" ||
                (visitor.outcome === "playing" && data.raceFinished)}
              class:visitor-playing={visitor.outcome === "playing" &&
                !data.raceFinished}>{visitor.displayName}</span
            >
            <span class="visitor-outcome"
              >{#if visitor.outcome === "backed"}↩{:else if visitor.outcome === "playing" && !data.raceFinished}⏳{:else if visitor.outcome === "abandoned" || (visitor.outcome === "playing" && data.raceFinished)}✗{/if}</span
            >
            <span class="visitor-deaths"
              >{#if visitor.deaths}<SkullIcon size={10} />
                {visitor.deaths}{/if}</span
            >
            <span class="visitor-weapons">
              {#if visitor.weapons && visitor.weapons.length > 0}
                <WeaponsPopover
                  combos={visitor.weapons}
                  maxRows={1}
                  showPercent={false}
                />
              {/if}
            </span>
            <span class="visitor-duration"
              >{#if visitor.timeSpentMs}{formatIgt(
                  visitor.timeSpentMs,
                )}{/if}</span
            >
            <span class="visitor-gap" class:behind={gapMs != null && gapMs > 0}
              >{#if gapMs != null}{formatGapCompact(gapMs)}{/if}</span
            >
          </div>
        {/each}
      </div>
    </div>
  {/if}

  {#if onzonecodex && (data.type === "legacy_dungeon" || data.type === "mini_dungeon")}
    {@const skipCount = skipCountForZones(data.zones)}
    <button
      class="codex-link"
      onclick={() => {
        onzonecodex(data.nodeId, data.displayName, data.zones);
        onclose();
      }}
    >
      {skipCount > 0
        ? `${skipCount} known skip${skipCount === 1 ? "" : "s"}`
        : "Zone codex"}
    </button>
  {/if}
</div>

<style>
  .node-popup {
    position: fixed;
    z-index: 100;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 12px 16px;
    min-width: 200px;
    max-width: 320px;
    max-height: 70vh;
    overflow-y: auto;
    box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
    font-size: 0.85rem;
    color: var(--color-text, #e8e6e1);
    pointer-events: auto;
  }

  .popup-header {
    margin-bottom: 8px;
  }

  .popup-title {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 8px;
  }

  .popup-name {
    font-size: 1rem;
    font-weight: 600;
    line-height: 1.3;
  }

  .popup-close {
    background: none;
    border: none;
    color: var(--color-text-secondary, #9ca3af);
    font-size: 1.2rem;
    cursor: pointer;
    padding: 0;
    line-height: 1;
    flex-shrink: 0;
  }

  .popup-close:hover {
    color: var(--color-text, #e8e6e1);
  }

  .popup-meta {
    display: flex;
    gap: 8px;
    align-items: center;
    margin-top: 2px;
  }

  .type-badge {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.07em;
  }

  .tier-badge {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--color-gold);
    padding: 0 0.3rem;
  }

  .layer-badge {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    margin-left: auto;
  }

  .popup-boss {
    font-size: 0.8rem;
    margin-top: 4px;
    color: var(--color-text-secondary, #9ca3af);
  }

  .boss-label {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    text-transform: uppercase;
    letter-spacing: 0.07em;
    color: var(--color-text-secondary);
  }

  .popup-section {
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
  }

  .section-title {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    color: var(--color-text-secondary);
    margin-bottom: 4px;
  }

  .conn-item {
    display: flex;
    align-items: flex-start;
    gap: 6px;
    padding: 2px 0;
  }

  .conn-arrow {
    font-size: 0.8rem;
    flex-shrink: 0;
  }

  .conn-arrow.entrance {
    color: var(--color-text-secondary, #9ca3af);
  }

  .conn-arrow.exit {
    color: var(--color-gold, #c8a44e);
  }

  .conn-details {
    display: flex;
    flex-direction: column;
    min-width: 0;
  }

  .conn-name {
    color: var(--color-text, #e8e6e1);
  }

  .conn-name.undiscovered {
    color: var(--color-text-disabled, #6b7280);
    font-style: italic;
  }

  .conn-text {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    color: var(--color-text-secondary);
    line-height: 1.3;
  }

  .player-list {
    display: flex;
    flex-wrap: wrap;
    gap: 6px;
  }

  .player-chip {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.8rem;
  }

  .player-dot {
    display: inline-block;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }

  /* Names stay in the UI face; only the digit cells below go mono. */
  .visitor-grid {
    display: grid;
    grid-template-columns: auto 1fr auto auto auto auto auto;
    gap: 2px 6px;
    font-size: 0.8rem;
  }

  /* Each visitor is a subgrid row so it can carry a background (the "me"
     tint) while its cells stay column-aligned across rows. The explicit
     column list is the fallback for pre-subgrid engines (old OBS/CEF):
     rows keep their layout, only cross-row alignment degrades. */
  .visitor-row {
    grid-column: 1 / -1;
    display: grid;
    grid-template-columns: auto 1fr auto auto auto auto auto;
    grid-template-columns: subgrid;
    column-gap: 6px;
    align-items: center;
  }

  /* Brass is the viewer's-own-run hue: "you" marks never ride fog */
  .visitor-row.me {
    background: rgba(200, 164, 78, 0.1);
    border-radius: var(--radius-sm);
  }

  .visitor-name {
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .visitor-backed {
    opacity: 0.6;
  }

  .visitor-abandoned {
    opacity: 0.4;
  }

  .visitor-playing {
    color: var(--color-gold, #c8a44e);
  }

  .visitor-outcome {
    font-size: 0.75rem;
    width: 1.2em;
    text-align: center;
  }

  .visitor-deaths {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--color-danger);
  }

  .visitor-weapons {
    display: inline-flex;
    align-items: center;
  }

  .visitor-duration {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--color-text-secondary);
    justify-self: end;
  }

  .visitor-gap {
    font-family: var(--font-mono);
    font-size: 0.75rem;
    justify-self: end;
  }

  .visitor-gap.behind {
    color: var(--color-gold);
  }

  .codex-link {
    display: block;
    width: 100%;
    margin-top: 10px;
    padding-top: 8px;
    border-top: 1px solid rgba(255, 255, 255, 0.06);
    background: none;
    border-left: none;
    border-right: none;
    border-bottom: none;
    text-align: right;
    font-size: 0.8rem;
    font-weight: 600;
    color: var(--color-purple, #8b5cf6);
    cursor: pointer;
  }

  .codex-link:hover {
    color: var(--color-purple-hover);
  }
</style>
