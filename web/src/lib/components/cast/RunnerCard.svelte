<script lang="ts">
  import { isOutOfRace } from "$lib/format";
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { formatGap } from "$lib/gap";
  import SkullIcon from "$lib/components/SkullIcon.svelte";

  interface SplitRow {
    zone: string;
    /** How long the runner spent in this zone. A split only exists once the
     * runner has left the zone (see `buildCastSplits`), so this is always a
     * real duration, never a placeholder. */
    durationMs: number;
  }

  interface Props {
    participant: WsParticipant;
    rank: number;
    avatarUrl: string | null;
    totalLayers: number | null;
    rect: Rect;
    variant: "card" | "mirror" | "tall";
    /** Rank 1: brass border, brass tint, brass rank digit. */
    leader: boolean;
    /** The race's own status: before the start the card carries no rank
     * (join order is the only order there is), the leader's gap row reads
     * Leader while it runs and Winner once it is over. */
    raceStatus: string;
    /** Node id -> label name (`DagNode.labelName`), from the seed's own graph
     * (`parseDagGraph(raceStore.seed.graph_json)`): `current_zone` on the
     * wire is a graph node id, never a display string. On a miss (the seed
     * hasn't resolved it yet) the zone line is left blank, same as
     * `Leaderboard.svelte`'s `zoneName`: a raw node id on a broadcast is
     * worse than nothing. */
    zoneNames?: Map<string, string> | null;
    /** The runner's last few zone splits, most recent first (see
     * `buildCastSplits`). Only the "tall" variant renders this; the quad
     * scene's cards pass nothing, so the section renders empty rather than
     * fabricating data for a card that has no room for it anyway. */
    splits?: SplitRow[];
    /** What the runner is wielding, already resolved to display names
     * ("Moonveil + Misericorde"); empty hides the line (catalogue still
     * loading, or nothing observed yet). Only the tall variant renders it:
     * the quad cards' height budget has no room a weapon line could take
     * legibly. No upgrade level on purpose: competitive modes play at max
     * upgrade, so it would be noise. */
    weapons?: string;
  }

  let {
    participant,
    rank,
    avatarUrl,
    totalLayers,
    rect,
    variant,
    leader,
    raceStatus,
    zoneNames = null,
    splits = [],
    weapons = "",
  }: Props = $props();

  let color = $derived(
    PLAYER_COLORS[participant.color_index % PLAYER_COLORS.length],
  );
  let badge = $derived(rewards.lookupBadge(participant.equipped_badge_id));
  let depth = $derived(
    Math.min(participant.current_layer + 1, totalLayers || Infinity),
  );
  // The cards sit beside their POVs in slot order, not in a ranked list, so
  // the leader's gap row names the role rather than standing blank (a
  // ranked list, the standings, keeps its usual empty cell).
  let ranked = $derived(raceStatus !== "setup");
  let leaderLabel = $derived(
    !leader || !ranked ? null : raceStatus === "finished" ? "Winner" : "Leader",
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

  // Node id -> display name, the same resolution and fallback as
  // Leaderboard.svelte's zoneName: on a broadcast, a raw node id like
  // "stormveil_godrick_48fd" reaching the screen in the window before
  // graph_json arrives is worse than the line sitting blank for a moment.
  // A route label is shortened to its last leg, but no character cap: the
  // CSS ellipsizes at the card's real width, which a count can only guess
  // (Leaderboard itself still caps at 20 for its narrow overlay column).
  function zoneLabel(zone: string | null): string {
    if (!zone) return "";
    const name = zoneNames?.get(zone);
    if (!name) return "";
    return name.includes(" - ") ? name.split(" - ").pop()! : name;
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
</script>

<div
  class="rcard"
  class:mirror={variant === "mirror"}
  class:tall={variant === "tall"}
  class:lead={leader && ranked}
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px; --c: {color};"
>
  <div class="chead">
    <span class="crk">{ranked ? rank : ""}</span>
    {#if avatarUrl}
      <img class="cav" src={avatarUrl} alt="" />
    {:else}
      <div class="cav placeholder"></div>
    {/if}
  </div>
  <span class="cname" style={nameStyleFor(participant)}
    ><span class="cname-text">{displayName(participant)}</span>{#if badge}<img
        src="/badges/{badge.icon_filename}"
        alt={badge.name}
        title={badge.name}
        class="card-badge"
      />{/if}</span
  >
  <!-- Every finisher stands in the final boss's zone: once the run is over,
       the line says so instead, the one place on the card that does. -->
  <span class="czone" class:finished={participant.status === "finished"}
    >{participant.status === "finished"
      ? "Finished"
      : zoneLabel(participant.current_zone)}</span
  >
  {#if weapons && variant === "tall"}
    <span class="cweap">{weapons}</span>
  {/if}
  <div class="crows">
    <div class="crow">
      <span class="ck">Depth</span>
      <span class="cv"
        >{depth}{#if totalLayers}<i>/{totalLayers}</i>{/if}</span
      >
    </div>
    <div class="crow">
      <span class="ck">Gap</span>
      <span
        class="cv"
        class:ahead={participant.gap_ms != null && participant.gap_ms < 0}
        class:behind={participant.gap_ms != null && participant.gap_ms > 0}
        class:dnf={isOutOfRace(participant.status)}
        class:role={leaderLabel !== null &&
          !isOutOfRace(participant.status) &&
          participant.gap_ms == null}
        >{#if participant.status === "disqualified"}DQ{:else if participant.status === "abandoned"}DNF{:else if participant.gap_ms != null}{formatGap(
            participant.gap_ms,
          )}{:else if leaderLabel}{leaderLabel}{/if}</span
      >
    </div>
    <div class="crow">
      <span class="ck">Deaths</span>
      <span class="cv"><SkullIcon size={19} />{participant.death_count}</span>
    </div>
    <div class="crow">
      <span class="ck">IGT</span>
      <span class="cv" class:finished={participant.status === "finished"}
        ><span class="sm">{formatIgt(participant.igt_ms)}</span></span
      >
    </div>
  </div>
  {#if variant === "tall"}
    <div class="splits">
      <span class="sp-t">Splits</span>
      {#each splits as s, i (i)}
        <div class="sp-r">
          <b>{s.zone}</b>
          <i>{formatIgt(s.durationMs)}</i>
        </div>
      {/each}
    </div>
  {/if}
</div>

<style>
  .rcard {
    position: absolute;
    display: flex;
    flex-direction: column;
    padding: 14px 16px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    /* The card has a fixed height from `rect`; nothing inside it, however a
     * future seed names a node, may spill past its edge onto the plate. */
    overflow: hidden;
  }

  /* The route colour that used to live on a separate dot now runs along
   * the card's top edge instead, the same line colour as the POV frame it
   * stands beside. */
  .rcard::before {
    content: "";
    position: absolute;
    left: -1px;
    right: -1px;
    top: -1px;
    height: 3px;
    background: var(--c, var(--color-gold));
  }

  .rcard.lead {
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

  .chead {
    display: flex;
    align-items: center;
    justify-content: space-between;
  }

  .crk {
    font-family: var(--font-mono);
    font-size: 42px;
    font-weight: 600;
    line-height: 1;
    color: var(--color-text-secondary);
  }

  .rcard.lead .crk {
    color: var(--color-gold);
  }

  .cav {
    width: 54px;
    height: 54px;
    object-fit: cover;
    border: 2px solid var(--c);
  }

  .cav.placeholder {
    background: var(--color-border);
  }

  /* The name keeps one line, ellipsized at the card's width (a 216px quad
   * card cut "SeriousChallenges" mid-letter), and the badge stays whole:
   * beside the name when both fit, on the next line when they don't. */
  .cname {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    margin-top: 8px;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 32px;
    letter-spacing: 0.02em;
    line-height: 1.05;
  }

  /* overflow: hidden clips at the line box, which at line-height 1.05 is
   * shorter than the face's descenders (g, j, p, q, y, _): the padding
   * gives them room, the negative margin takes it back out of the layout. */
  .cname-text {
    min-width: 0;
    max-width: 100%;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    padding-block: 0.15em;
    margin-block: -0.15em;
  }

  .card-badge {
    width: 22px;
    height: 22px;
    margin-left: 0.25rem;
    flex-shrink: 0;
  }

  /* One line, clipped by the card's own width: the zone name is cut by
   * the CSS, not by a character count that would trim names which fit.
   * Never squeezed by the card's flex column either: with overflow hidden
   * it would otherwise give up its whole height first (a hero whose badge
   * wraps under its name, over a two-line weapon, lost the zone entirely). */
  .czone {
    flex-shrink: 0;
    margin-top: 2px;
    font-size: 20px;
    color: var(--color-text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .czone.finished {
    color: var(--color-info);
  }

  .crows {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: space-evenly;
    margin-top: 6px;
  }

  .crow {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 10px;
    padding-top: 8px;
    border-top: 1px solid var(--color-border);
  }

  .ck {
    font-family: var(--font-display);
    font-size: 21px;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  .cv {
    display: flex;
    align-items: center;
    gap: 6px;
    font-family: var(--font-mono);
    font-size: 27px;
    font-weight: 600;
  }

  .cv i {
    font-style: normal;
    font-size: 17px;
    color: var(--color-text-secondary);
  }

  .cv .sm {
    font-size: 20px;
    font-weight: 400;
  }

  .cv.behind {
    color: var(--color-danger);
  }

  .cv.ahead {
    color: var(--color-success);
  }

  /* DNF is a state, not an alarm: the secondary text colour, not ember. */
  .cv.dnf {
    color: var(--color-text-secondary);
  }

  /* Leader / Winner: a role, not a time, so the card's display face in the
   * leader's brass rather than a mono number. */
  .cv.role {
    font-family: var(--font-display);
    font-size: 24px;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--color-gold);
  }

  /* A finished runner's time is their result: the finished colour the duel
   * cards and the standings give it too. */
  .cv.finished {
    color: var(--color-info);
  }

  /* The hero's wielded combo, under the zone line: a full-width line of
   * its own, no label, because a labelled stats row leaves the card too
   * little width for real weapon names. Up to two lines, then ellipsis;
   * never squeezed by the card's own flex column. Only the tall variant
   * renders it (see the template). */
  .cweap {
    margin-top: 4px;
    font-family: var(--font-mono);
    font-size: 17px;
    line-height: 1.3;
    flex-shrink: 0;
    display: -webkit-box;
    -webkit-box-orient: vertical;
    -webkit-line-clamp: 2;
    line-clamp: 2;
    overflow: hidden;
  }

  .rcard.mirror .chead {
    flex-direction: row-reverse;
  }

  .rcard.mirror .cname {
    justify-content: flex-end;
  }

  .rcard.mirror .cname,
  .rcard.mirror .czone {
    text-align: right;
  }

  .rcard.tall {
    padding: 18px 18px 20px;
  }

  .rcard.tall .cav {
    width: 118px;
    height: 118px;
  }

  .rcard.tall .crk {
    font-size: 52px;
  }

  .rcard.tall .cname {
    margin-top: 14px;
    font-size: 38px;
  }

  .rcard.tall .card-badge {
    width: 26px;
    height: 26px;
  }

  .rcard.tall .czone {
    font-size: 20px;
  }

  .rcard.tall .crows {
    flex: none;
    margin-top: 16px;
  }

  .rcard.tall .crow {
    padding: 14px 0 6px;
  }

  .rcard.tall .ck {
    font-size: 24px;
  }

  .rcard.tall .cv {
    font-size: 32px;
  }

  /* The tall card's values grow to 32px; its role label follows in step. */
  .rcard.tall .cv.role {
    font-size: 28px;
  }

  .rcard.tall .cv .sm {
    font-size: 24px;
  }

  /* The one block that yields when the tall card runs short of height (a
   * badge wrapped under the name, a two-line weapon): it shrinks, and a
   * split row that no longer fits wraps into a second column, off to the
   * right where the card's overflow hides it, so rows drop whole instead of
   * being cut. */
  .splits {
    margin-top: auto;
    padding-top: 12px;
    min-height: 0;
    flex: 0 1 auto;
    display: flex;
    flex-direction: column;
    flex-wrap: wrap;
    align-content: flex-start;
    overflow: hidden;
  }

  .splits > * {
    width: 100%;
  }

  .sp-t {
    display: block;
    margin-bottom: 6px;
    font-family: var(--font-display);
    font-size: 22px;
    font-weight: 500;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--color-text-disabled);
  }

  .sp-r {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 8px;
    padding: 5px 0;
    /* Literal fallback first; see the note on .rcard.lead's background. */
    border-top: 1px solid rgba(37, 53, 80, 0.55);
    border-top: 1px solid
      color-mix(in srgb, var(--color-border) 55%, transparent);
  }

  .sp-r b {
    flex: 1 1 auto;
    min-width: 0;
    font-family: var(--font-family);
    font-weight: 400;
    font-size: 16px;
    color: var(--color-text-secondary);
    /* One line, always: a shortened name (see buildCastSplits) is meant to
     * fit, but nothing here should be able to wrap and push the row (and
     * the splits block behind it) past the card's fixed height. */
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .sp-r i {
    flex-shrink: 0;
    font-style: normal;
    font-family: var(--font-mono);
    font-size: 16px;
    color: var(--color-text);
  }
</style>
