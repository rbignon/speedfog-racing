<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { formatGap } from "$lib/gap";

  interface Props {
    /** Already rank-ordered (raceStore.leaderboard): row `i` is rank `i + 1`,
     * and the leader's `gap_ms` is always null by construction (see the race
     * store's `computeGap`), which is what makes its gap cell blank below
     * without special-casing the first row. */
    participants: WsParticipant[];
    totalLayers: number | null;
    rect: Rect;
  }

  let { participants, totalLayers, rect }: Props = $props();

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
  {#each participants as p, i (p.id)}
    {@const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length]}
    {@const depth = Math.min(p.current_layer + 1, totalLayers || Infinity)}
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
      <span class="dep"
        >{depth}{#if totalLayers}<i>/{totalLayers}</i>{/if}</span
      >
    </div>
  {/each}
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

  .dep {
    font-family: var(--font-mono);
    font-size: 18px;
    font-weight: 600;
    text-align: right;
    flex-shrink: 0;
    min-width: 44px;
  }

  .dep i {
    font-style: normal;
    font-size: 14px;
    color: var(--color-text-secondary);
  }
</style>
