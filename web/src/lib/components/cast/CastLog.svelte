<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { CastLogRow } from "$lib/cast/log";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import SkullIcon from "$lib/components/SkullIcon.svelte";

  interface Props {
    /** Newest first, already capped to what the panel fits (see the metro
     * page's `buildCastLog` call): this component only renders rows, it
     * doesn't decide how many. */
    rows: CastLogRow[];
    rect: Rect;
  }

  let { rows, rect }: Props = $props();

  // Duplicated in every card that shows an IGT (RunnerCard, Leaderboard,
  // LeaderboardOverlay, ...), this codebase's established way of formatting
  // one rather than a shared helper.
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
</script>

<div
  class="log"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px;"
>
  <span class="blk-title">Latest</span>
  {#each rows as row (row.id + "-" + row.igtMs)}
    {@const color = PLAYER_COLORS[row.colorIndex % PLAYER_COLORS.length]}
    {@const died = (row.deaths ?? 0) > 0}
    <div class="fl">
      <span class="ft">{formatIgt(row.igtMs)}</span>
      <span class="fn" style="color: {color};">{row.name}</span>
      <span class="fe" class:dead={died}
        >{#if died}<SkullIcon size={14} /> died in {row.zone}{:else}&rarr;
          {row.zone}{/if}</span
      >
    </div>
  {/each}
</div>

<style>
  .log {
    position: absolute;
    display: flex;
    flex-direction: column;
  }

  .blk-title {
    display: block;
    margin-bottom: 8px;
    font-family: var(--font-display);
    font-size: 24px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  .fl {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 31px;
    font-family: var(--font-mono);
    font-size: 18px;
    color: var(--color-text-secondary);
  }

  .ft {
    color: var(--color-text-disabled);
  }

  /* A resolved zone name here is the whole route label ("Ancient Ruins of
   * Rauh - Romina, Saint of the Bud"), not shortened (unlike CastStandings'
   * zoneLabel): the log's job is what just happened, where the full label
   * is the information. Its exposure is a layout one, not a data one: one
   * line, clipped with an ellipsis rather than wrapping into the next row
   * or spilling into the standings panel 16px to the right. The player
   * name cell carries the same guard for the same reason (a long Twitch
   * display name is the same kind of unbounded string). `min-width: 0`
   * overrides the flex item's default auto min-width (which would sit at
   * the full unwrapped content width and defeat the guard); `display:
   * inline-block` is what makes `overflow`/`text-overflow` apply at all,
   * since both are no-ops on a plain inline box (mirrors CastMiniStandings'
   * and CastStandings' own `.nm`). */
  .fn {
    display: inline-block;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 24px;
    letter-spacing: 0.02em;
  }

  .fe {
    display: inline-block;
    flex: 1;
    min-width: 0;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .fe.dead {
    color: var(--color-danger);
  }
</style>
