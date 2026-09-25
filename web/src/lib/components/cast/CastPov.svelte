<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";

  interface Props {
    rect: Rect;
    /** null while the slot's runner hasn't been resolved yet (an unassigned
     * seat, or the leaderboard hasn't connected): draws the frame and slot
     * chip in a neutral colour, with no nameplate. */
    participant: WsParticipant | null;
    slot: number;
    /** Whether to print the runner's name at the bottom-left. False on the
     * quad scene, where the card standing beside the hole already names the
     * runner; true for a hole with no card next to it (the focus scene's
     * small POVs and hero). */
    nameplate: boolean;
  }

  let { rect, participant, slot, nameplate }: Props = $props();

  let lineColor = $derived(
    participant
      ? PLAYER_COLORS[participant.color_index % PLAYER_COLORS.length]
      : "var(--color-border)",
  );

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
  // attribute and silently drop the whole style. Mirrors
  // LeaderboardOverlay.svelte's nameStyleFor.
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
  class="pov"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px; --c: {lineColor};"
>
  <span class="slot">{slot}</span>
  {#if nameplate && participant}
    <span class="np">
      <span class="npn" style={nameStyleFor(participant)}
        >{displayName(participant)}</span
      >
    </span>
  {/if}
</div>

<style>
  /* The video itself is an OBS source composited beneath this browser
   * layer (see CastPlate's mask): this component only ever draws the frame
   * around the hole, never anything inside it. */
  .pov {
    position: absolute;
    outline: 3px solid var(--c);
    box-shadow:
      0 0 0 1px #000,
      0 0 26px 6px rgba(0, 0, 0, 0.55);
  }

  .slot {
    position: absolute;
    left: 0;
    top: 0;
    width: 30px;
    height: 30px;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--c);
    color: var(--color-ink-on-accent);
    font-family: var(--font-mono);
    font-weight: 600;
    font-size: 18px;
  }

  .np {
    position: absolute;
    left: 0;
    bottom: 0;
    padding: 6px 16px;
    background: color-mix(in srgb, var(--color-bg) 86%, transparent);
  }

  .npn {
    display: inline-block;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 28px;
    letter-spacing: 0.02em;
  }
</style>
