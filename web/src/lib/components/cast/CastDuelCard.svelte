<script lang="ts">
  import { isOutOfRace } from "$lib/format";
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import SkullIcon from "$lib/components/SkullIcon.svelte";

  interface Props {
    participant: WsParticipant;
    rank: number;
    avatarUrl: string | null;
    totalLayers: number | null;
    rect: Rect;
    /** The right card faces inward, toward the versus block, the same way
     * the quad scene's right column mirrors its cards toward their POV. */
    mirrored: boolean;
    /** Rank 1: brass border and rank digit, like RunnerCard. */
    leader: boolean;
    /** Node id -> display name, from the seed's own graph: `current_zone`
     * on the wire is a graph node id, never a display string. On a miss the
     * zone line is left blank, same as RunnerCard's zoneLabel. */
    zoneNames?: Map<string, string> | null;
    /** What the runner is wielding, already resolved to display names
     * ("Moonveil + Misericorde"); empty hides the line (catalogue still
     * loading, or nothing observed yet). No upgrade level on purpose:
     * competitive modes play at max upgrade, so it would be noise. */
    weapons?: string;
  }

  let {
    participant,
    rank,
    avatarUrl,
    totalLayers,
    rect,
    mirrored,
    leader,
    zoneNames = null,
    weapons = "",
  }: Props = $props();

  let color = $derived(
    PLAYER_COLORS[participant.color_index % PLAYER_COLORS.length],
  );
  let badge = $derived(rewards.lookupBadge(participant.equipped_badge_id));
  let depth = $derived(
    Math.min(participant.current_layer + 1, totalLayers || Infinity),
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
  // attribute and silently drop the whole style. Mirrors RunnerCard's
  // nameStyleFor.
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

  // A route label is shortened to its last leg, but no character cap: the
  // CSS ellipsizes at the card's real width, which a count can only guess.
  function zoneLabel(zone: string | null): string {
    if (!zone) return "";
    const name = zoneNames?.get(zone);
    if (!name) return "";
    return name.includes(" - ") ? name.split(" - ").pop()! : name;
  }

  // Duplicated in every card that shows an IGT (RunnerCard, CastLog, ...),
  // this codebase's established way of formatting one rather than a shared
  // helper.
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

  // A stale zone under a runner who is out reads as if they were still
  // racing there: the out-of-race state replaces it, in the same quiet
  // secondary tone the standings use for DNF/DQ.
  let zoneLine = $derived(
    participant.status === "disqualified"
      ? "DQ"
      : participant.status === "abandoned"
        ? "DNF"
        : zoneLabel(participant.current_zone),
  );
</script>

<div
  class="dcard"
  class:mirror={mirrored}
  class:lead={leader}
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px; --c: {color};"
>
  <div class="dhead">
    {#if avatarUrl}
      <img class="dav" src={avatarUrl} alt="" />
    {:else}
      <div class="dav placeholder"></div>
    {/if}
    <div class="dwho">
      <span class="dname" style={nameStyleFor(participant)}
        >{displayName(participant)}{#if badge}<img
            src="/badges/{badge.icon_filename}"
            alt={badge.name}
            title={badge.name}
            class="dbadge"
          />{/if}</span
      >
      <span class="dzone" class:out={isOutOfRace(participant.status)}
        >{zoneLine}</span
      >
    </div>
    <span class="drk">{rank}</span>
  </div>
  {#if weapons}
    <span class="dweap">{weapons}</span>
  {/if}
  <div class="dstats">
    <div class="dstat">
      <span class="dk">Depth</span>
      <span class="dv"
        >{depth}{#if totalLayers}<i>/{totalLayers}</i>{/if}</span
      >
    </div>
    <div class="dstat">
      <span class="dk">Deaths</span>
      <span class="dv"><SkullIcon size={19} />{participant.death_count}</span>
    </div>
    <div class="dstat">
      <span class="dk">IGT</span>
      <span class="dv digt" class:finished={participant.status === "finished"}
        >{formatIgt(participant.igt_ms)}</span
      >
    </div>
  </div>
</div>

<style>
  .dcard {
    position: absolute;
    display: flex;
    flex-direction: column;
    justify-content: space-between;
    padding: 14px 16px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    overflow: hidden;
  }

  /* The route colour runs along the card's top edge, the same line colour
   * as the POV frame it stands beneath. */
  .dcard::before {
    content: "";
    position: absolute;
    left: -1px;
    right: -1px;
    top: -1px;
    height: 3px;
    background: var(--c, var(--color-gold));
  }

  .dcard.lead {
    border: 2px solid var(--color-gold);
    /* Literal fallback first: OBS builds in the field still ship Chromium
     * 103, which predates color-mix() (needs 111), and an unsupported value
     * anywhere in a shorthand drops the whole declaration, not just that
     * stop. */
    background:
      linear-gradient(
        180deg,
        rgba(200, 164, 78, 0.1),
        rgba(200, 164, 78, 0.03)
      ),
      var(--color-surface);
    background:
      linear-gradient(
        180deg,
        color-mix(in srgb, var(--color-gold) 10%, transparent),
        color-mix(in srgb, var(--color-gold) 3%, transparent)
      ),
      var(--color-surface);
  }

  .dhead {
    display: flex;
    align-items: center;
    gap: 14px;
    min-height: 0;
  }

  .dav {
    width: 72px;
    height: 72px;
    object-fit: cover;
    border: 2px solid var(--c);
    flex-shrink: 0;
  }

  .dav.placeholder {
    background: var(--color-border);
  }

  .dwho {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
  }

  .dname {
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 30px;
    letter-spacing: 0.02em;
    line-height: 1.05;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .dbadge {
    width: 22px;
    height: 22px;
    margin-left: 0.25rem;
    vertical-align: middle;
  }

  .dzone {
    margin-top: 2px;
    font-size: 17px;
    color: var(--color-text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .drk {
    font-family: var(--font-mono);
    font-size: 42px;
    font-weight: 600;
    line-height: 1;
    color: var(--color-text-secondary);
    flex-shrink: 0;
  }

  .dcard.lead .drk {
    color: var(--color-gold);
  }

  .dstats {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    padding-top: 10px;
    border-top: 1px solid var(--color-border);
  }

  .dstat {
    display: flex;
    align-items: baseline;
    gap: 8px;
  }

  .dk {
    font-family: var(--font-display);
    font-size: 19px;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  .dv {
    display: flex;
    align-items: center;
    gap: 5px;
    font-family: var(--font-mono);
    font-size: 24px;
    font-weight: 600;
  }

  .dv i {
    font-style: normal;
    font-size: 16px;
    color: var(--color-text-secondary);
  }

  /* A finished runner's time is their result: the same finished colour the
   * standings' final-time cell uses. */
  .digt.finished {
    color: var(--color-info);
  }

  /* The wielded combo, between the head and the stats row. A paired combo
   * of long names ellipsizes rather than growing the card. */
  .dweap {
    font-family: var(--font-mono);
    font-size: 18px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .dcard.mirror .dhead {
    flex-direction: row-reverse;
  }

  .dcard.mirror .dwho {
    text-align: right;
  }

  .dcard.mirror .dweap {
    text-align: right;
  }

  .dcard.mirror .dstats {
    flex-direction: row-reverse;
  }

  .dcard.mirror .dstat {
    flex-direction: row-reverse;
  }
</style>
