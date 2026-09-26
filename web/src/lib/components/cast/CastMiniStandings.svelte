<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { formatGap } from "$lib/gap";
  import { rowCapacity, planRows } from "$lib/cast/rows";

  interface Props {
    /** Already rank-ordered (raceStore.leaderboard): row `i` is rank `i + 1`,
     * and the leader's `gap_ms` is always null by construction (see the race
     * store's `computeGap`), which is what makes its gap cell blank below
     * without special-casing the first row. */
    participants: WsParticipant[];
    rect: Rect;
  }

  let { participants, rect }: Props = $props();

  // The panel can never overflow: how many rows fit comes from this rect's
  // own height, not a typed number, the same rowCapacity/planRows the
  // metro scene's CastStandings uses. No title here (unlike CastStandings):
  // the reserve is .clb's own padding (4px top + 4px bottom) and border
  // (1px top + 1px bottom) below, unchanged from the mockup. ROW_HEIGHT is
  // .lrow's own height, matching the validated mockup's .lrow (height:33px).
  const CHROME_RESERVE = 10;
  const ROW_HEIGHT = 33;
  let capacity = $derived(rowCapacity(rect.h, CHROME_RESERVE, ROW_HEIGHT));
  let plan = $derived(planRows(participants, capacity));

  function displayName(p: WsParticipant): string {
    return p.twitch_display_name || p.twitch_username;
  }

  function templateFor(p: WsParticipant) {
    const id = p.equipped_name_template_id;
    if (!id || id === "default") return null;
    return rewards.lookupTemplate(id);
  }

  // Applied through a Svelte style binding, never concatenated into HTML: a
  // template's name_css can carry a double-quoted value (the Pioneer
  // template's "Times New Roman"), which would close an HTML-built style
  // attribute and silently drop the whole style. Mirrors RunnerCard's and
  // CastPov's nameStyleFor.
  function nameStyleFor(p: WsParticipant): string {
    const t = templateFor(p);
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

<div
  class="clb"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px;"
>
  {#each plan.visible as p, i (p.id)}
    {@const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length]}
    <div class="lrow" style="--c: {color};">
      <span class="rk" class:first={i === 0}>{i + 1}</span>
      <span class="dot"></span>
      <span class="nm" style={nameStyleFor(p)}>{displayName(p)}</span>
      <span
        class="gap"
        class:ahead={p.gap_ms != null && p.gap_ms < 0}
        class:behind={p.gap_ms != null && p.gap_ms > 0}
        class:dnf={p.status === "abandoned"}
        >{#if p.status === "abandoned"}DNF{:else if p.gap_ms != null}{formatGap(
            p.gap_ms,
          )}{/if}</span
      >
    </div>
  {/each}
  {#if plan.hiddenCount > 0}
    <div class="lrow more">
      <span class="more-text">+ {plan.hiddenCount} more</span>
    </div>
  {/if}
</div>

<style>
  .clb {
    position: absolute;
    display: flex;
    flex-direction: column;
    justify-content: center;
    padding: 4px 12px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
  }

  .lrow {
    display: flex;
    align-items: center;
    gap: 10px;
    height: 33px;
  }

  .rk {
    font-family: var(--font-mono);
    font-size: 19px;
    font-weight: 600;
    color: var(--color-text-secondary);
    width: 20px;
    text-align: center;
    flex-shrink: 0;
  }

  .rk.first {
    color: var(--color-gold);
  }

  .dot {
    width: 10px;
    height: 10px;
    border-radius: 50%;
    background: var(--c);
    flex-shrink: 0;
  }

  /* No depth cell here any more: the focus scene's own POVs already show
   * what each runner is doing, the same reasoning that dropped
   * CastStandings' depth column, and this panel is only 320px wide, so a
   * cell that only restates the map/POV was the weakest use of its width. */
  .nm {
    flex: 1;
    min-width: 0;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 24px;
    letter-spacing: 0.02em;
    display: inline-block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .gap {
    font-family: var(--font-mono);
    font-size: 20px;
    font-weight: 600;
    text-align: right;
    flex-shrink: 0;
    min-width: 60px;
  }

  .gap.behind {
    color: var(--color-danger);
  }

  .gap.ahead {
    color: var(--color-success);
  }

  /* DNF is a state, not an alarm: the secondary text colour, not ember.
   * Mirrors RunnerCard's own Gap row. */
  .gap.dnf {
    color: var(--color-text-secondary);
  }

  /* A quiet line, not a shout: same row rhythm as the data above it, but
   * plain secondary-coloured text instead of columns. Mirrors the in-game
   * overlay's own "+ N more" footer for the same situation. */
  .lrow.more {
    color: var(--color-text-secondary);
  }

  .more-text {
    font-family: var(--font-mono);
    font-size: 16px;
    letter-spacing: 0.04em;
  }
</style>
