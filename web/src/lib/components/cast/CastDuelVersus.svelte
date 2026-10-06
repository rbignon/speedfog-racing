<script lang="ts">
  import { isOutOfRace } from "$lib/format";
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { formatGap } from "$lib/gap";

  interface Props {
    /** The two seated runners, left and right, in POV order (not rank
     * order): the block sits between their POVs, so each side's numbers
     * stay under that runner's own video. Either seat may be empty. */
    a: WsParticipant | null;
    b: WsParticipant | null;
    rect: Rect;
    totalLayers: number | null;
  }

  let { a, b, rect, totalLayers }: Props = $props();

  function displayName(p: WsParticipant): string {
    return p.twitch_display_name || p.twitch_username;
  }

  function colorOf(p: WsParticipant): string {
    return PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
  }

  function depthOf(p: WsParticipant): number {
    return Math.min(p.current_layer + 1, totalLayers || Infinity);
  }

  // Neither side can change the outcome any more: finished, or out.
  function done(p: WsParticipant): boolean {
    return p.status === "finished" || isOutOfRace(p.status);
  }

  // The duel's own gap: the two seated runners against each other, not
  // against the field's leader (a showcase race can hold more runners than
  // the scene seats). Both gap_ms values share the leader's reference, so
  // their difference is the head-to-head gap; a side out of the race has no
  // live gap to show, and the surviving side leads by default. Once neither
  // side is still racing, the side ahead has won rather than leads.
  let duel = $derived.by(() => {
    if (!a || !b) return null;
    const settled = done(a) && done(b);
    const outA = isOutOfRace(a.status);
    const outB = isOutOfRace(b.status);
    if (outA || outB) {
      return {
        gapText: "–",
        leader: outA === outB ? null : outA ? b : a,
        settled,
      };
    }
    // Two playing runners with no computed gap yet (the splits still in
    // flight, or held back by the caster delay) is unknown, not a tie:
    // only the field leader legitimately carries a null gap.
    if (
      a.gap_ms == null &&
      b.gap_ms == null &&
      a.status === "playing" &&
      b.status === "playing"
    ) {
      return { gapText: "–", leader: null, settled };
    }
    const diff = (a.gap_ms ?? 0) - (b.gap_ms ?? 0);
    if (diff === 0) return { gapText: "0:00", leader: null, settled };
    return {
      gapText: formatGap(Math.abs(diff)),
      leader: diff > 0 ? b : a,
      settled,
    };
  });
</script>

<div
  class="versus"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px;"
>
  {#if a && b && duel}
    <!-- Each side's depth stands next to that runner's own card, the gap
         between them; deaths stay on the cards rather than repeated here. -->
    <div class="vcol">
      <span class="vk">Depth</span>
      <span class="vside vl-a" style="--c: {colorOf(a)};"
        >{depthOf(a)}{#if totalLayers}<i>/{totalLayers}</i>{/if}</span
      >
    </div>
    <div class="vcol vmain">
      <span class="vk">Gap</span>
      <span class="vgap">{duel.gapText}</span>
      {#if duel.leader}
        <span class="vlead" style="--c: {colorOf(duel.leader)};"
          >{displayName(duel.leader)} {duel.settled ? "wins" : "leads"}</span
        >
      {/if}
    </div>
    <div class="vcol">
      <span class="vk">Depth</span>
      <span class="vside vl-b" style="--c: {colorOf(b)};"
        >{depthOf(b)}{#if totalLayers}<i>/{totalLayers}</i>{/if}</span
      >
    </div>
  {:else}
    <span class="vempty">VS</span>
  {/if}
</div>

<style>
  .versus {
    position: absolute;
    display: flex;
    align-items: stretch;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
  }

  .vcol {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 8px;
    padding: 12px;
  }

  .vcol + .vcol {
    border-left: 1px solid var(--color-border);
  }

  /* The gap is the block's one headline number: the side columns support
   * it, they never compete with it. */
  .vmain {
    flex: 1.4;
  }

  .vk {
    font-family: var(--font-display);
    font-size: 21px;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  .vside {
    font-family: var(--font-mono);
    font-size: 44px;
    font-weight: 600;
    line-height: 1.1;
    /* The runner's route colour underlines whose number this is, the same
     * line colour as the POV frame above it. */
    border-bottom: 3px solid var(--c, var(--color-border));
    padding: 0 4px 2px;
  }

  .vside i {
    font-style: normal;
    font-size: 24px;
    color: var(--color-text-secondary);
  }

  .vgap {
    font-family: var(--font-mono);
    font-size: 56px;
    font-weight: 600;
    line-height: 1;
  }

  .vlead {
    font-family: var(--font-display);
    font-size: 20px;
    font-weight: 500;
    letter-spacing: 0.03em;
    color: var(--c, var(--color-text-secondary));
  }

  .vempty {
    margin: auto;
    font-family: var(--font-display);
    font-size: 40px;
    font-weight: 600;
    letter-spacing: 0.1em;
    color: var(--color-text-disabled);
  }
</style>
