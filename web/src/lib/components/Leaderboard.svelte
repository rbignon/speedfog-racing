<script lang="ts">
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import LiveBadge from "./LiveBadge.svelte";
  import { rewards } from "$lib/stores/rewards.svelte";
  import WeaponsPopover from "./WeaponsPopover.svelte";
  import { aggregateAllCombos } from "$lib/weapons";
  import { formatGapCompact } from "$lib/gap";

  interface Props {
    participants: WsParticipant[];
    totalLayers?: number | null;
    mode?: "running" | "finished";
    zoneNames?: Map<string, string> | null;
    // Gates display of the competitor info that would spoil an in-progress
    // run: current zone, death count, weapon loadout. The owning page
    // computes this from race state (status, my participant, late-join
    // window, private-DAG flag, organizer override). The IGT, status, and
    // identity remain visible regardless.
    showRunDetails?: boolean;
    // Deathless race: an abandoned participant with at least one death was
    // eliminated by the rule, shown as "Dead" instead of "Abandoned".
    deathless?: boolean;
    selectedIds?: Set<string>;
    onToggle?: (id: string, ctrlKey: boolean) => void;
    onClearSelection?: () => void;
  }

  let {
    participants,
    totalLayers = null,
    mode = "running",
    zoneNames = null,
    showRunDetails = false,
    deathless = false,
    selectedIds,
    onToggle,
    onClearSelection,
  }: Props = $props();

  let hasSelection = $derived(selectedIds != null && selectedIds.size > 0);

  function zoneName(zone: string | null): string | null {
    if (!zone || !zoneNames) return null;
    const name = zoneNames.get(zone);
    if (!name) return null;
    const short = name.includes(" - ") ? name.split(" - ").pop()! : name;
    if (short.length > 20) return short.slice(0, 19) + "\u2026";
    return short;
  }

  function playerColor(participant: WsParticipant): string {
    return PLAYER_COLORS[participant.color_index % PLAYER_COLORS.length];
  }

  function formatIgt(ms: number): string {
    const totalSeconds = Math.floor(ms / 1000);
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
    }
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  }

  function templateFor(participant: WsParticipant) {
    const id = participant.equipped_name_template_id;
    if (!id || id === "default") return null;
    return rewards.lookupTemplate(id);
  }

  // The player's line color never colors the name: without a template the
  // name stays default ink, the line lives on the row's left border.
  function nameStyleFor(participant: WsParticipant): string {
    const t = templateFor(participant);
    const parts: string[] = [];
    if (t?.gradient) {
      parts.push(
        `background: linear-gradient(90deg, ${t.gradient[0]}, ${t.gradient[1]});`,
        "-webkit-background-clip: text;",
        "background-clip: text;",
        "color: transparent;",
        "padding-inline-end: 0.1em;",
      );
    } else if (t?.color) {
      parts.push(`color: ${t.color};`);
    }
    if (t?.name_css) {
      parts.push(t.name_css);
    }
    return parts.join(" ");
  }

  function backgroundStyleFor(participant: WsParticipant): string {
    const t = templateFor(participant);
    return t?.background_css ? `background: ${t.background_css};` : "";
  }
</script>

<svelte:window
  onkeydown={(e) => {
    if (e.key === "Escape" && hasSelection && onClearSelection) {
      onClearSelection();
    }
  }}
/>

<div class="leaderboard">
  {#if participants.length === 0}
    <p class="empty">No participants yet</p>
  {:else}
    <ol class="list" class:has-selection={hasSelection}>
      {#each participants as participant, index (participant.id)}
        {@const color = playerColor(participant)}
        {@const badge = rewards.lookupBadge(participant.equipped_badge_id)}
        {@const isPlaying = participant.status === "playing"}
        {@const isAbandoned = participant.status === "abandoned"}
        {@const isDead =
          isAbandoned && deathless && participant.death_count > 0}
        {@const isFinished = participant.status === "finished"}
        {@const isPreRace =
          participant.status === "ready" || participant.status === "registered"}
        {@const isSelected = selectedIds?.has(participant.id) ?? false}
        {@const zone =
          isPlaying && showRunDetails
            ? zoneName(participant.current_zone)
            : null}
        <!-- svelte-ignore a11y_no_noninteractive_tabindex -->
        <li
          class="participant"
          class:abandoned={isAbandoned}
          class:selected={isSelected}
          style="--player-color: {color}; {backgroundStyleFor(participant)}"
          onclick={(e) => onToggle?.(participant.id, e.ctrlKey || e.metaKey)}
          role={onToggle ? "button" : undefined}
          tabindex={onToggle ? 0 : undefined}
        >
          {#if onToggle && hasSelection}
            <button
              type="button"
              class="select-box"
              class:checked={isSelected}
              aria-pressed={isSelected}
              aria-label="Toggle {participant.twitch_display_name ||
                participant.twitch_username} for comparison"
              title="Add to comparison"
              onclick={(e) => {
                e.stopPropagation();
                onToggle?.(participant.id, true);
              }}
              >{#if isSelected}✓{/if}</button
            >
          {/if}
          <span class="rank">{index + 1}.</span>
          <div class="info">
            <div class="name-row">
              <span class="name name-container">
                <a
                  href="/user/{participant.twitch_username}"
                  target="_blank"
                  class="name-link"
                  style={nameStyleFor(participant)}
                  onclick={(e) => e.stopPropagation()}
                >
                  {#if mode === "running" && (isPlaying || isPreRace)}
                    <span
                      class="conn-dot"
                      class:connected={participant.mod_connected}
                      title={participant.mod_connected
                        ? "Mod connected"
                        : "Mod disconnected"}
                    ></span>
                  {/if}<span
                    >{participant.twitch_display_name ||
                      participant.twitch_username}</span
                  >
                </a>
                {#if badge}
                  <img
                    src="/badges/{badge.icon_filename}"
                    alt={badge.name}
                    title={badge.name}
                    class="participant-badge"
                  />
                {/if}
              </span>
              {#if participant.is_live}
                <LiveBadge
                  href={participant.stream_url ??
                    `https://twitch.tv/${participant.twitch_username}`}
                  small
                  onclick={(e) => e.stopPropagation()}
                />
              {/if}
              {#if mode === "finished" && participant.daily_points != null}
                <!-- Qualified finishers and abandoners both earn points on a
                     closed daily; the abandoner's layer moves to the
                     Abandoned line below. -->
                <span class="points-earned">+{participant.daily_points}</span>
              {:else if isPlaying}
                <span class="layer-fraction"
                  >{Math.min(
                    participant.current_layer + 1,
                    totalLayers || Infinity,
                  )}{totalLayers ? `/${totalLayers}` : ""}</span
                >
              {:else if isFinished && mode === "running"}
                <span class="finish-icon">✓</span>
              {/if}
            </div>
            {#if isAbandoned}
              <span class="zone abandoned-label">
                <span>{isDead ? "Dead" : "DNF"}</span>
                {#if totalLayers}
                  <span class="abandoned-layers"
                    >{Math.min(
                      participant.current_layer + 1,
                      totalLayers,
                    )}/{totalLayers}</span
                  >
                {/if}
              </span>
            {:else if zone}
              <span
                class="zone"
                title={zoneNames?.get(participant.current_zone ?? "") ?? ""}
                >{zone}</span
              >
            {/if}
            <span class="stats">
              {#if isPlaying || isAbandoned || isFinished}
                <span class="time" class:finished-time={isFinished}
                  >{formatIgt(participant.igt_ms)}</span
                >
                {#if participant.gap_ms != null && !hasSelection}
                  <span
                    class="gap"
                    class:ahead={participant.gap_ms < 0}
                    class:behind={participant.gap_ms > 0}
                    >{formatGapCompact(participant.gap_ms)}</span
                  >
                {/if}
                <span class="stats-right">
                  {#if showRunDetails && participant.death_count > 0}
                    <span class="death-count">{participant.death_count}</span>
                  {/if}
                  {#if showRunDetails && participant.zone_history}
                    {@const combos = aggregateAllCombos(
                      participant.zone_history,
                    )}
                    {#if combos.length > 0}
                      <WeaponsPopover
                        {combos}
                        minPercent={1}
                        title="{participant.twitch_display_name ??
                          participant.twitch_username}'s loadout"
                      />
                    {/if}
                  {/if}
                </span>
              {:else}
                <span class="status-text">{participant.status}</span>
              {/if}
            </span>
          </div>
        </li>
      {/each}
    </ol>
  {/if}

  {#if hasSelection && onClearSelection}
    <button type="button" class="clear-pill" onclick={onClearSelection}>
      <span class="count">{selectedIds!.size}</span> selected ×
    </button>
  {/if}
</div>

<style>
  .leaderboard {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
    position: relative;
  }

  .select-box {
    width: 15px;
    height: 15px;
    flex-shrink: 0;
    padding: 0;
    border-radius: 2px;
    border: 1px solid var(--color-border);
    background: transparent;
    display: flex;
    align-items: center;
    justify-content: center;
    font-family: inherit;
    font-size: 0.65rem;
    line-height: 1;
    font-weight: 900;
    color: transparent;
    cursor: pointer;
    opacity: 0.4;
    /* Tighten the gap to the rank badge (the row gap is 0.75rem). */
    margin-right: -0.25rem;
    transition:
      opacity var(--transition),
      background var(--transition),
      border-color var(--transition);
  }

  .participant:hover .select-box {
    opacity: 1;
  }

  .select-box:hover {
    border-color: var(--color-text-secondary);
  }

  .select-box.checked {
    opacity: 1;
    background: var(--player-color);
    border-color: var(--player-color);
    color: #14100a;
  }

  .clear-pill {
    position: absolute;
    bottom: 0.6rem;
    right: 0.6rem;
    z-index: 5;
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.25rem 0.7rem;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-radius: 999px;
    color: var(--color-text-secondary);
    font-family: inherit;
    font-size: var(--font-size-sm);
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
    transition:
      color var(--transition),
      border-color var(--transition);
  }

  .clear-pill:hover {
    color: var(--color-text);
    border-color: var(--color-text-secondary);
  }

  .clear-pill .count {
    color: var(--color-text);
    font-weight: 600;
  }

  .list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    flex: 1;
    border-top: 1px solid var(--color-border);
  }

  .list.has-selection {
    /* Leave room so the last row can scroll clear of the floating clear pill. */
    padding-bottom: 2.75rem;
  }

  .participant {
    position: relative;
    display: flex;
    align-items: center;
    gap: 0.6rem;
    padding: 0.55rem 0.5rem 0.6rem 0.9rem;
    border-bottom: 1px solid var(--color-border);
    transition: background var(--transition);
    cursor: pointer;
  }

  /* The player's metro line: a 3px inset bar, never the name itself */
  .participant::before {
    content: "";
    position: absolute;
    left: 0;
    top: 9px;
    bottom: 9px;
    width: 3px;
    background: var(--player-color);
  }

  .participant:hover {
    background: var(--color-surface-elevated);
  }

  .participant.selected {
    background: var(--color-surface-elevated);
  }

  .participant.abandoned {
    opacity: 0.55;
  }

  .rank {
    width: 20px;
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.72rem;
    text-align: right;
    color: var(--color-text-secondary);
  }

  .info {
    flex: 1;
    min-width: 0;
  }

  .name {
    display: block;
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .name-link {
    display: inline;
    text-decoration: none;
    color: inherit;
  }

  .name-link:hover {
    text-decoration: underline;
  }

  .stats {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.75rem;
    color: var(--color-text-secondary);
  }

  /* Fixed-width time column so the gap that follows lands in the same place on
     every row, independent of time length (M:SS vs H:MM:SS) or death count.
     Sized to fit a single-digit-hour H:MM:SS at --font-size-sm; a 10h+ run
     would grow past it and nudge only that row's gap, which is implausible
     for this domain. */
  .time {
    flex: 0 0 auto;
    min-width: 3.4rem;
  }

  .stats-right {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    flex-shrink: 0;
    white-space: nowrap;
    margin-left: auto;
  }

  .gap {
    flex-shrink: 0;
    font-variant-numeric: tabular-nums;
  }

  .gap.ahead {
    color: var(--color-success);
  }

  .gap.behind {
    color: var(--color-gold);
  }

  .finished-time {
    color: var(--color-success);
    font-weight: 500;
    font-variant-numeric: tabular-nums;
  }

  .status-text {
    text-transform: capitalize;
  }

  .finish-icon {
    color: var(--color-success);
    font-size: 1.2rem;
    flex-shrink: 0;
    margin-left: auto;
  }

  .points-earned {
    color: var(--color-success);
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    font-weight: 500;
    flex-shrink: 0;
    margin-left: auto;
  }

  .death-count {
    color: var(--color-danger);
  }

  .death-count::before {
    content: "† ";
    margin-left: 0.25em;
  }

  .zone.abandoned-label {
    color: var(--color-text-secondary);
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.5rem;
  }

  .abandoned-layers {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 0.72rem;
  }

  .name-row {
    display: flex;
    align-items: baseline;
    gap: 0.5rem;
  }

  .name-row .name {
    flex: 0 1 auto;
    min-width: 0;
  }

  .layer-fraction {
    font-family: var(--font-mono);
    font-size: 0.72rem;
    color: var(--color-text-secondary);
    flex-shrink: 0;
    margin-left: auto;
  }

  .zone {
    display: block;
    font-size: var(--font-size-sm);
    color: var(--color-text);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .conn-dot {
    display: inline-block;
    width: 6px;
    height: 6px;
    border-radius: 50%;
    background: var(--color-text-disabled, #555);
    margin-right: 0.4rem;
    vertical-align: middle;
  }

  .conn-dot.connected {
    background: var(--color-success, #22c55e);
  }

  .empty {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .participant-badge {
    width: 18px;
    height: 18px;
    vertical-align: middle;
    margin-left: 0.25rem;
    flex-shrink: 0;
  }
</style>
