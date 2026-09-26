<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { EventStageEntry, User } from "$lib/api";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { rowCapacity, planRows } from "$lib/cast/rows";

  interface Props {
    rect: Rect;
    /** The stage's own label ("Semi B"), for the "Semi B standings" title. */
    label: string;
    /** How many of the evening's races have a race attached, for the
     * "After N of M races" eyebrow. */
    racesPlayed: number;
    racesExpected: number;
    /** Already ranked by the server (`stage.results`): row `i` is rank `i + 1`. */
    results: EventStageEntry[];
  }

  let { rect, label, racesPlayed, racesExpected, results }: Props = $props();

  // The panel can never overflow: how many rows fit comes from this rect's
  // own height, not a typed number. HEADER_RESERVE is the eyebrow + title
  // block above the rows (.standings' own 2px top padding, .seyebrow's
  // font-size 14, .stitle's 4px/14px margins and font-size 40, none of
  // which scale with the field). ROW_HEIGHT is .srow's own height,
  // unchanged from the validated mockup (.srow height:72px). There is no
  // caster override here (unlike the metro scene's CastStandings): the
  // stage decides how many runners exist, not the caster.
  const HEADER_RESERVE = 2 + 14 + 4 + 40 + 14;
  const ROW_HEIGHT = 72;
  let capacity = $derived(rowCapacity(rect.h, HEADER_RESERVE, ROW_HEIGHT));
  let plan = $derived(planRows(results, capacity));

  function displayName(u: User): string {
    return u.twitch_display_name || u.twitch_username;
  }

  function templateFor(u: User) {
    const id = u.equipped_name_template_id;
    if (!id || id === "default") return null;
    return rewards.lookupTemplate(id);
  }

  // Applied through a Svelte style binding, never concatenated into HTML: a
  // template's name_css can carry a double-quoted value (the Pioneer
  // template's "Times New Roman"), which would close an HTML-built style
  // attribute and silently drop the whole style. Mirrors RunnerCard's,
  // CastPov's, CastStandings' and CastMiniStandings' own nameStyleFor.
  function nameStyleFor(u: User): string {
    const t = templateFor(u);
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

  function initial(u: User): string {
    return displayName(u).charAt(0).toUpperCase();
  }
</script>

<!--
  Deliberately not a card: no plate, no border. A standings block that looked
  like a fourth race card would read as a fourth race, which is exactly the
  confusion this shape exists to avoid (see the separator to its left).
-->
<div
  class="standings"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px;"
>
  <span class="seyebrow">After {racesPlayed} of {racesExpected} races</span>
  <span class="stitle">{label} standings</span>
  {#if results.length === 0}
    <span class="sempty">Standings arrive after the first race finishes.</span>
  {:else}
    {#each plan.visible as entry, i (entry.user.id)}
      <div class="srow" class:adv={entry.advances}>
        <span class="srk">{i + 1}</span>
        {#if entry.user.twitch_avatar_url}
          <img class="sav" src={entry.user.twitch_avatar_url} alt="" />
        {:else}
          <span class="sav sav-placeholder">{initial(entry.user)}</span>
        {/if}
        <span class="sn" style={nameStyleFor(entry.user)}
          >{displayName(entry.user)}</span
        >
        {#if entry.advances}<span class="stag">Final</span>{/if}
        <span class="sp">{entry.points}</span>
      </div>
    {/each}
    {#if plan.hiddenCount > 0}
      <div class="srow more">
        <span class="more-text">+ {plan.hiddenCount} more</span>
      </div>
    {/if}
  {/if}
</div>

<style>
  .standings {
    position: absolute;
    display: flex;
    flex-direction: column;
    padding: 2px 0 0 30px;
  }

  .seyebrow {
    font-family: var(--font-mono);
    font-size: 14px;
    letter-spacing: 0.16em;
    text-transform: uppercase;
    color: var(--color-text-disabled);
  }

  .stitle {
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 40px;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    line-height: 1;
    margin: 4px 0 14px;
  }

  /* Reads as "empty on purpose", not broken: the talk scene holds this
   * frame longest, before any race in the stage has a result to show. */
  .sempty {
    max-width: 90%;
    color: var(--color-text-secondary);
    font-size: 22px;
    line-height: 1.35;
  }

  .srow {
    display: flex;
    align-items: center;
    gap: 14px;
    height: 72px;
  }

  .srow + .srow {
    /* Literal fallback first: OBS builds in the field still ship Chromium
     * 103, which predates color-mix() (needs 111). */
    border-top: 1px solid rgba(37, 53, 80, 0.55);
    border-top: 1px solid
      color-mix(in srgb, var(--color-border) 55%, transparent);
  }

  /* The runner is through: the row steps outside the block's own left
   * padding to carry a brass rule the others don't have. */
  .srow.adv {
    margin-left: -30px;
    padding-left: 27px;
    border-left: 3px solid var(--color-gold);
  }

  .srk {
    font-family: var(--font-mono);
    font-size: 22px;
    font-weight: 600;
    color: var(--color-text-secondary);
    width: 16px;
    flex-shrink: 0;
  }

  .sav {
    width: 46px;
    height: 46px;
    object-fit: cover;
    border: 1px solid var(--color-border);
    flex-shrink: 0;
  }

  .sav-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface-elevated);
    color: var(--color-text-secondary);
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 20px;
  }

  .sn {
    flex: 1;
    min-width: 0;
    font-family: var(--font-display);
    font-size: 31px;
    font-weight: 600;
    letter-spacing: 0.02em;
    display: inline-block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .stag {
    font-family: var(--font-mono);
    font-size: 12px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    color: var(--color-gold);
    /* Literal fallback first; see the note on .srow + .srow above. */
    border: 1px solid rgba(200, 164, 78, 0.5);
    border: 1px solid color-mix(in srgb, var(--color-gold) 50%, transparent);
    padding: 2px 7px;
    flex-shrink: 0;
  }

  .sp {
    font-family: var(--font-mono);
    font-size: 34px;
    font-weight: 600;
    color: var(--color-gold);
    min-width: 62px;
    text-align: right;
    flex-shrink: 0;
  }

  /* A quiet line, not a shout: same row rhythm as the data above it, but
   * plain secondary-coloured text instead of columns. Mirrors the in-game
   * overlay's own "+ N more" footer for the same situation. */
  .srow.more {
    color: var(--color-text-secondary);
  }

  .more-text {
    font-family: var(--font-mono);
    font-size: 22px;
    letter-spacing: 0.04em;
  }
</style>
