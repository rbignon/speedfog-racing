<script lang="ts">
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { formatGapCompact } from "$lib/gap";

  interface Props {
    participants: WsParticipant[];
  }

  let { participants }: Props = $props();

  let finishers = $derived(
    participants.filter((p) => p.status === "finished").slice(0, 3),
  );

  const PLACE_TAGS = ["1st", "2nd", "3rd"];

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

  function playerColor(p: WsParticipant): string {
    return PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
  }

  // Names render through the equipped name template; without one they stay
  // default ink (the player's line color lives on the column's top edge).
  function nameStyleFor(p: WsParticipant): string {
    const id = p.equipped_name_template_id;
    const t = !id || id === "default" ? null : rewards.lookupTemplate(id);
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
</script>

{#if finishers.length > 0}
  <div class="finish-board">
    {#each finishers as finisher, place (finisher.id)}
      <div
        class="fb-col"
        class:win={place === 0}
        style="--line: {playerColor(finisher)}"
      >
        <span class="fb-place">{PLACE_TAGS[place]}</span>
        <div class="fb-name" style={nameStyleFor(finisher)}>
          {finisher.twitch_display_name || finisher.twitch_username}
        </div>
        <div class="fb-time">{formatIgt(finisher.igt_ms)}</div>
        <div class="fb-sub">
          {#if place > 0}
            {formatGapCompact(finisher.igt_ms - finishers[0].igt_ms)}
          {/if}
          {#if place > 0 && finisher.death_count > 0}&middot;{/if}
          {#if finisher.death_count > 0}
            &dagger; {finisher.death_count}
            death{finisher.death_count !== 1 ? "s" : ""}
          {/if}
        </div>
      </div>
    {/each}
  </div>
{/if}

<style>
  .finish-board {
    display: grid;
    grid-auto-columns: 1fr;
    grid-auto-flow: column;
    flex-shrink: 0;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    background: var(--color-surface);
    overflow: hidden;
  }

  .fb-col {
    position: relative;
    padding: 1rem 1.1rem 0.85rem;
    border-left: 1px solid var(--color-border);
    min-width: 0;
  }

  .fb-col:first-child {
    border-left: none;
  }

  /* The player's line runs along the column's top edge, closed by a
   * small terminal square. */
  .fb-col::before {
    content: "";
    position: absolute;
    top: 0;
    left: 0;
    right: 0;
    height: 2px;
    background: var(--line);
  }

  .fb-col::after {
    content: "";
    position: absolute;
    top: 5px;
    right: 8px;
    width: 7px;
    height: 7px;
    background: var(--line);
  }

  .fb-place {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.12em;
    text-transform: uppercase;
    color: var(--color-gold);
  }

  .fb-name {
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 1.2rem;
    letter-spacing: 0.02em;
    margin: 0.05rem 0 0.1rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .fb-time {
    font-family: var(--font-mono);
    font-size: 1rem;
    color: var(--color-text);
  }

  .fb-col.win .fb-time {
    font-size: 1.25rem;
  }

  .fb-sub {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--color-text-secondary);
    margin-top: 2px;
    min-height: 1em;
  }

  @media (max-width: 640px) {
    .finish-board {
      grid-auto-flow: row;
    }

    .fb-col {
      border-left: none;
      border-top: 1px solid var(--color-border);
    }

    .fb-col:first-child {
      border-top: none;
    }
  }
</style>
