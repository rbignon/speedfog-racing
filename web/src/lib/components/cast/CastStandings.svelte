<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { formatGap } from "$lib/gap";
  import { rowCapacity, planRows } from "$lib/cast/rows";
  import SkullIcon from "$lib/components/SkullIcon.svelte";

  interface Props {
    /** Already rank-ordered (raceStore.leaderboard): row `i` is rank `i + 1`,
     * and the leader's `gap_ms` is always null by construction (see the race
     * store's `computeGap`), which is what makes its gap cell blank below
     * without special-casing the first row. */
    participants: WsParticipant[];
    totalLayers: number | null;
    /** Node id -> display name, from the seed's own graph
     * (`parseDagGraph(raceStore.seed.graph_json)`): `current_zone` on the
     * wire is a graph node id, never a display string. */
    zoneNames: Map<string, string>;
    rect: Rect;
    /** Caster override for how many rows to show, from the metro scene's own
     * `lines` URL parameter (see `/overlay/race/[id]/leaderboard`, which
     * reads the same name for the same reason): `null` or omitted fits as
     * many as the panel allows. Never raises the count past what the panel
     * actually fits: a caster can ask for fewer rows, never for overflow. */
    lines?: number | null;
  }

  let {
    participants,
    totalLayers,
    zoneNames,
    rect,
    lines = null,
  }: Props = $props();

  // The panel can never overflow: how many rows fit comes from this rect's
  // own height, not a typed number, so a bigger field (or a resized panel)
  // never prints past the panel's bottom. .blk-title reserves font-size (24)
  // + margin-bottom (8) = 32, the same title-reserve convention the metro
  // page's own log-row cap already uses; ROW_HEIGHT is .rrow's own height
  // below, unchanged from the validated mockup (docs/superpowers/specs/
  // 2026-09-23-cast-overlays-mockup.py's CSS, .rrow height:45px).
  const TITLE_RESERVE = 32;
  const ROW_HEIGHT = 45;
  let capacity = $derived(rowCapacity(rect.h, TITLE_RESERVE, ROW_HEIGHT));
  let effectiveCapacity = $derived(
    lines != null && lines > 0 ? Math.min(capacity, lines) : capacity,
  );
  let plan = $derived(planRows(participants, effectiveCapacity));

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
  // CastMiniStandings' nameStyleFor.
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

  // A resolved node name is a whole route label ("Gravesite Plain - Fog
  // Rift Catacombs - Death Knight"), not a short zone name: strip the
  // region prefix and cap the length, exactly like RunnerCard.zoneLabel and
  // $lib/cast/splits.ts's own zoneLabel do for the same data (duplicated
  // rather than shared, this codebase's established way of shortening a
  // node name). Without it this column overflowed the row, the earlier bug
  // this same treatment already fixed once.
  const ZONE_LABEL_MAX = 20;
  function zoneLabel(zone: string | null): string {
    if (!zone) return "";
    const name = zoneNames.get(zone);
    if (!name) return "";
    const short = name.includes(" - ") ? name.split(" - ").pop()! : name;
    return short.length > ZONE_LABEL_MAX
      ? short.slice(0, ZONE_LABEL_MAX - 1) + "…"
      : short;
  }
</script>

<div
  class="rank"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px;"
>
  <span class="blk-title">Standings</span>
  {#each plan.visible as p, i (p.id)}
    {@const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length]}
    {@const depth = Math.min(p.current_layer + 1, totalLayers || Infinity)}
    <div class="rrow" style="--c: {color};">
      <span class="rk" class:first={i === 0}>{i + 1}</span>
      <span class="dot"></span>
      <span class="nm" style={nameStyleFor(p)}>{displayName(p)}</span>
      <span class="rzone">{zoneLabel(p.current_zone)}</span>
      <span class="dth"><SkullIcon size={17} />{p.death_count}</span>
      <span class="layer"
        >{depth}{#if totalLayers}<i>/{totalLayers}</i>{/if}</span
      >
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
    <div class="rrow more">
      <span class="more-text">+ {plan.hiddenCount} more</span>
    </div>
  {/if}
</div>

<style>
  .rank {
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

  .rrow {
    display: flex;
    align-items: center;
    gap: 14px;
    height: 45px;
    padding: 0 4px;
    border-top: 1px solid var(--color-border);
  }

  .rk {
    font-family: var(--font-mono);
    font-size: 24px;
    font-weight: 600;
    color: var(--color-text-secondary);
    width: 24px;
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
    flex: none;
    min-width: 210px;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 27px;
    letter-spacing: 0.02em;
    display: inline-block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .rzone {
    flex: 1;
    min-width: 0;
    font-size: 19px;
    color: var(--color-text-secondary);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .dth {
    display: flex;
    align-items: center;
    gap: 6px;
    min-width: 64px;
    font-family: var(--font-mono);
    font-size: 19px;
    color: var(--color-text-secondary);
    flex-shrink: 0;
  }

  .layer {
    min-width: 80px;
    font-family: var(--font-mono);
    font-size: 26px;
    font-weight: 600;
    text-align: right;
    flex-shrink: 0;
  }

  .layer i {
    font-style: normal;
    font-size: 17px;
    color: var(--color-text-secondary);
  }

  .gap {
    min-width: 120px;
    font-family: var(--font-mono);
    font-size: 26px;
    font-weight: 600;
    text-align: right;
    flex-shrink: 0;
  }

  .gap.behind {
    color: var(--color-danger);
  }

  .gap.ahead {
    color: var(--color-success);
  }

  /* DNF is a state, not an alarm: the secondary text colour, not ember.
   * Mirrors RunnerCard's and CastMiniStandings' own Gap row. */
  .gap.dnf {
    color: var(--color-text-secondary);
  }

  /* A quiet line, not a shout: same row rhythm as the data above it, but
   * plain secondary-coloured text instead of columns. Mirrors the in-game
   * overlay's own "+ N more" footer for the same situation. */
  .rrow.more {
    color: var(--color-text-secondary);
  }

  .more-text {
    font-family: var(--font-mono);
    font-size: 20px;
    letter-spacing: 0.04em;
  }
</style>
