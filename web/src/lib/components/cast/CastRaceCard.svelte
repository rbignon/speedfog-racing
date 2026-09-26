<script lang="ts">
  import type { Rect } from "$lib/cast/layout";
  import type { EventStageRace, EventFieldSlot, User } from "$lib/api";
  import { rewards } from "$lib/stores/rewards.svelte";
  import { rowCapacity, planRows } from "$lib/cast/rows";

  interface Props {
    rect: Rect;
    /** 1-based position of this card in the evening ("Race 1"), independent
     * of whether a race has been attached to it yet. */
    slot: number;
    /** The stage's mode label for this slot (`stage.modes[i]`). */
    mode: string | undefined;
    /** The race filling this slot, or null while the evening hasn't reached
     * it yet: the card then falls back to `field` below. */
    entry: EventStageRace | null;
    /** The stage's expected field, shown while `entry` is null. */
    field: EventFieldSlot[];
  }

  let { rect, slot, mode, entry, field }: Props = $props();

  type CardStatus = "live" | "finished" | "upcoming";

  let status = $derived<CardStatus>(
    entry?.race.status === "running"
      ? "live"
      : entry?.race.status === "finished"
        ? "finished"
        : "upcoming",
  );
  let statusText = $derived(
    status === "live"
      ? "Live"
      : status === "finished"
        ? "Finished"
        : "Upcoming",
  );
  // Mirrors CastDesk's own live/finished/upcoming palette, so a card reads
  // the same way as the desk's own status pill.
  let accent = $derived(
    status === "live"
      ? "var(--color-danger)"
      : status === "finished"
        ? "var(--color-info)"
        : "var(--color-text-disabled)",
  );

  interface Row {
    key: string;
    name: string;
    nameStyle: string;
    tbd: boolean;
    right: string;
  }

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

  // A race carries no per-runner point value of its own: only the stage's
  // running total does (see CastRoundStandings). What a specific race does
  // give each finisher is their time, so that's what the result cell shows;
  // a runner who hasn't finished this race yet gets a blank cell rather than
  // a guessed number.
  let rows = $derived<Row[]>(
    entry
      ? entry.race.participant_previews.map((p) => ({
          key: p.id,
          name: displayName(p),
          nameStyle: nameStyleFor(p),
          tbd: false,
          right:
            p.status === "finished" && p.igt_ms != null
              ? formatIgt(p.igt_ms)
              : "",
        }))
      : field.map((seat, i) => ({
          key: seat.user?.id ?? `tbd-${i}`,
          name: seat.user ? displayName(seat.user) : seat.label,
          nameStyle: seat.user ? nameStyleFor(seat.user) : "",
          tbd: seat.user === null,
          right: "",
        })),
  );

  // The card can never overflow: how many rows fit comes from this rect's
  // own height, not a typed number. HEADER_RESERVE is everything the rows
  // list doesn't get: .bracket's own 16px top+bottom padding, .bhead's
  // line (.brn font-size 30), and .bst's block (6px/14px margins + 13px
  // font-size), none of which grow with the field. ROW_HEIGHT is .brow's
  // own height, unchanged from the validated mockup (.brow height:56px).
  const HEADER_RESERVE = 16 + 16 + 30 + (6 + 13 + 14);
  const ROW_HEIGHT = 56;
  let capacity = $derived(rowCapacity(rect.h, HEADER_RESERVE, ROW_HEIGHT));
  let plan = $derived(planRows(rows, capacity));
</script>

<div
  class="bracket"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px; --c: {accent};"
>
  <div class="bhead">
    <span class="brn">Race {slot}</span>
    {#if mode}<span class="bmode">{mode}</span>{/if}
  </div>
  <span class="bst {status}">{statusText}</span>
  {#each plan.visible as row (row.key)}
    <div class="brow">
      <span class="bn" class:tbd={row.tbd} style={row.nameStyle}
        >{row.name}</span
      >
      <span class="bp" class:prov={row.right === ""}>{row.right}</span>
    </div>
  {/each}
  {#if plan.hiddenCount > 0}
    <div class="brow more">
      <span class="more-text">+ {plan.hiddenCount} more</span>
    </div>
  {/if}
</div>

<style>
  .bracket {
    position: absolute;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    padding: 16px 18px;
    display: flex;
    flex-direction: column;
  }

  .bracket::before {
    content: "";
    position: absolute;
    left: -1px;
    right: -1px;
    top: -1px;
    height: 3px;
    background: var(--c, var(--color-gold));
  }

  .bhead {
    display: flex;
    align-items: baseline;
    gap: 12px;
  }

  .brn {
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 30px;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  .bmode {
    font-family: var(--font-mono);
    font-size: 15px;
    color: var(--color-text-secondary);
    letter-spacing: 0.04em;
  }

  .bst {
    font-family: var(--font-mono);
    font-size: 13px;
    letter-spacing: 0.14em;
    text-transform: uppercase;
    margin: 6px 0 14px;
  }

  .bst.finished {
    color: var(--color-info);
  }

  .bst.live {
    color: var(--color-danger);
  }

  .bst.upcoming {
    color: var(--color-text-disabled);
  }

  .brow {
    display: flex;
    align-items: center;
    gap: 12px;
    height: 56px;
    border-top: 1px solid var(--color-border);
  }

  .bn {
    flex: 1;
    min-width: 0;
    font-family: var(--font-display);
    font-size: 26px;
    font-weight: 500;
    letter-spacing: 0.02em;
    display: inline-block;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  /* A field seat nobody has filled yet: the source stage's placeholder
   * label ("Top 2 of Quarter C"), styled like the web page's own .tbd. */
  .bn.tbd {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .bp {
    font-family: var(--font-mono);
    font-size: 23px;
    font-weight: 600;
    color: var(--color-gold);
    min-width: 44px;
    text-align: right;
    flex-shrink: 0;
  }

  .bp.prov {
    opacity: 0.75;
  }

  /* A quiet line, not a shout: same row rhythm as the data above it, but
   * plain secondary-coloured text instead of columns. Mirrors the in-game
   * overlay's own "+ N more" footer for the same situation. */
  .brow.more {
    color: var(--color-text-secondary);
  }

  .more-text {
    font-family: var(--font-mono);
    font-size: 18px;
    letter-spacing: 0.04em;
  }
</style>
