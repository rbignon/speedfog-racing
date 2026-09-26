<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { WsParticipant } from "$lib/websocket";
  import { PLAYER_COLORS } from "$lib/dag/constants";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { formatGap } from "$lib/gap";
  import { rowCapacity, capRows } from "$lib/cast/rows";
  import SkullIcon from "$lib/components/SkullIcon.svelte";

  interface Props {
    /** Already rank-ordered (raceStore.leaderboard): row `i` is rank `i + 1`,
     * and the leader's `gap_ms` is always null by construction (see the race
     * store's `computeGap`), which is what makes its gap cell blank below
     * without special-casing the first row. */
    participants: WsParticipant[];
    totalLayers: number | null;
    rect: Rect;
    /** Caster override for how many rows to show, from the metro scene's own
     * `lines` URL parameter (see `/overlay/race/[id]/leaderboard`, which
     * reads the same name for the same reason): `null` or omitted fits as
     * many as the panel allows. Never raises the count past what the panel
     * actually fits: a caster can ask for fewer rows, never for overflow. */
    lines?: number | null;
  }

  let { participants, totalLayers, rect, lines = null }: Props = $props();

  // The panel can never overflow: how many rows fit comes from this rect's
  // own height, not a typed number. .blk-title reserves font-size (24) +
  // margin-bottom (8) = 32 (now carried by .title-row, see below); ROW_HEIGHT
  // is .rrow's own height, unchanged from the validated mockup
  // (docs/superpowers/specs/2026-09-23-cast-overlays-mockup.py's CSS,
  // .rrow height:45px). The panel reads two columns wide (this rect's own
  // 972px width comfortably fits two ~475px columns with a gutter once the
  // zone column below is gone), so the total capacity is twice what one
  // column holds; there is no row spent on an overflow line here (see
  // title-more below), unlike CastMiniStandings/CastRoundStandings/
  // CastRaceCard, so capRows (not planRows) is what caps the field.
  const TITLE_RESERVE = 32;
  const ROW_HEIGHT = 45;
  const COLUMNS = 2;
  let perColumnCapacity = $derived(
    rowCapacity(rect.h, TITLE_RESERVE, ROW_HEIGHT),
  );
  let totalCapacity = $derived(perColumnCapacity * COLUMNS);
  let effectiveCapacity = $derived(
    lines != null && lines > 0 ? Math.min(totalCapacity, lines) : totalCapacity,
  );
  let plan = $derived(capRows(participants, effectiveCapacity));
  // Reading order is down the first column then down the second: the first
  // perColumnCapacity ranks go left, the rest go right.
  let col1 = $derived(plan.visible.slice(0, perColumnCapacity));
  let col2 = $derived(plan.visible.slice(perColumnCapacity));

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
</script>

{#snippet row(p: WsParticipant, rank: number)}
  {@const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length]}
  {@const depth = Math.min(p.current_layer + 1, totalLayers || Infinity)}
  <div class="rrow" style="--c: {color};">
    <span class="rk" class:first={rank === 1}>{rank}</span>
    <span class="dot"></span>
    <span class="nm" style={nameStyleFor(p)}>{displayName(p)}</span>
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
{/snippet}

<div
  class="rank"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px;"
>
  <div class="title-row">
    <span class="blk-title">Standings</span>
    {#if plan.hiddenCount > 0}
      <span class="title-more">+ {plan.hiddenCount} more</span>
    {/if}
  </div>
  <div class="columns">
    <div class="column">
      {#each col1 as p, i (p.id)}
        {@render row(p, i + 1)}
      {/each}
    </div>
    <div class="column">
      {#each col2 as p, i (p.id)}
        {@render row(p, col1.length + i + 1)}
      {/each}
    </div>
  </div>
</div>

<style>
  .rank {
    position: absolute;
    display: flex;
    flex-direction: column;
  }

  .title-row {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 12px;
    margin-bottom: 8px;
  }

  .blk-title {
    font-family: var(--font-display);
    font-size: 24px;
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  /* The overflow count moves up here instead of spending a row on it (see
   * CastMiniStandings/CastRoundStandings/CastRaceCard for the row-based
   * version): this panel is only 230px tall, so that row is worth buying
   * back. Same phrasing as those, still a quiet line, not a shout. */
  .title-more {
    flex-shrink: 0;
    font-family: var(--font-mono);
    font-size: 18px;
    letter-spacing: 0.04em;
    color: var(--color-text-secondary);
  }

  .columns {
    display: flex;
    flex: 1;
    gap: 24px;
    min-height: 0;
  }

  .column {
    flex: 1;
    min-width: 0;
    display: flex;
    flex-direction: column;
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

  /* The column's own flexible cell (flex:1, min-width:0), the same
   * shrink-and-ellipsis role .rzone (the now-removed zone column) used to
   * play: without a zone column there is nothing else in the row to give
   * ground, and a narrower per-column width means a long name needs to.
   * Mirrors CastMiniStandings' own .nm, which has never had a zone column
   * to lean on either. */
  .nm {
    flex: 1;
    min-width: 0;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 27px;
    letter-spacing: 0.02em;
    display: inline-block;
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
</style>
