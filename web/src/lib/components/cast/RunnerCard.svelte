<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { formatGap } from "$lib/gap";
  import SkullIcon from "$lib/components/SkullIcon.svelte";

  interface SplitRow {
    zone: string;
    /** Gap to the leader at this split, ms (negative = ahead); null shows
     * the dim placeholder. */
    gapMs: number | null;
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
    /** Node id -> display name, from the seed's own graph
     * (`parseDagGraph(raceStore.seed.graph_json)`): `current_zone` on the
     * wire is a graph node id, never a display string. Falls back to the
     * raw id when the seed hasn't resolved it yet, same as
     * `$lib/cast/log`'s `buildCastLog`. */
    zoneNames?: Map<string, string> | null;
    /** The runner's last few zone splits. Only the "tall" variant renders
     * this (the focus scene's panel, the next task); every caller here
     * passes nothing, so the section renders empty rather than fabricating
     * data no caller yet computes. */
    splits?: SplitRow[];
  }

  let {
    participant,
    rank,
    avatarUrl,
    totalLayers,
    rect,
    variant,
    leader,
    zoneNames = null,
    splits = [],
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

  // Node id -> short display name, matching Leaderboard.svelte's zoneName
  // (same 20-char truncation and "A - B" -> "B" convention), except the
  // fallback: a caster-facing overlay shows the raw id rather than hiding
  // the zone outright when the seed hasn't resolved it yet.
  function zoneLabel(zone: string | null): string {
    if (!zone) return "";
    const name = zoneNames?.get(zone);
    if (!name) return zone;
    const short = name.includes(" - ") ? name.split(" - ").pop()! : name;
    return short.length > 20 ? short.slice(0, 19) + "…" : short;
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
  class:lead={leader}
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px; --c: {color};"
>
  <div class="chead">
    <span class="crk">{rank}</span>
    {#if avatarUrl}
      <img class="cav" src={avatarUrl} alt="" />
    {:else}
      <div class="cav placeholder"></div>
    {/if}
  </div>
  <span class="cname" style={nameStyleFor(participant)}
    >{displayName(participant)}{#if badge}<img
        src="/badges/{badge.icon_filename}"
        alt={badge.name}
        title={badge.name}
        class="card-badge"
      />{/if}</span
  >
  <span class="czone">{zoneLabel(participant.current_zone)}</span>
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
        class:dim={participant.gap_ms == null}
        >{participant.gap_ms != null
          ? formatGap(participant.gap_ms)
          : "-"}</span
      >
    </div>
    <div class="crow">
      <span class="ck">Deaths</span>
      <span class="cv"><SkullIcon size={19} />{participant.death_count}</span>
    </div>
    <div class="crow">
      <span class="ck">IGT</span>
      <span class="cv"
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
          <i>{s.gapMs != null ? formatGap(s.gapMs) : "-"}</i>
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

  .cname {
    display: inline-block;
    margin-top: 8px;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 32px;
    letter-spacing: 0.02em;
    line-height: 1.05;
  }

  .card-badge {
    width: 22px;
    height: 22px;
    margin-left: 0.25rem;
    vertical-align: middle;
    flex-shrink: 0;
  }

  .czone {
    margin-top: 2px;
    font-size: 17px;
    color: var(--color-text-secondary);
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

  .cv.dim {
    color: var(--color-text-disabled);
  }

  .rcard.mirror .chead {
    flex-direction: row-reverse;
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

  .rcard.tall .cv .sm {
    font-size: 24px;
  }

  .splits {
    margin-top: auto;
    padding-top: 12px;
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
    border-top: 1px solid
      color-mix(in srgb, var(--color-border) 55%, transparent);
  }

  .sp-r b {
    font-family: var(--font-family);
    font-weight: 400;
    font-size: 16px;
    color: var(--color-text-secondary);
  }

  .sp-r i {
    font-style: normal;
    font-family: var(--font-mono);
    font-size: 16px;
    color: var(--color-text);
  }
</style>
