<script lang="ts">
  import type { Snippet } from "svelte";
  import type { EventStage } from "$lib/api";
  import {
    DATE_TO_BE_AGREED,
    bracketLayout,
    fillSlots,
    linkPath,
    stageWinner,
    stripStagePrefix,
  } from "$lib/events";
  import EventStageBox, {
    type StageChip,
    type StageRow,
  } from "./EventStageBox.svelte";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
  import UserLink from "$lib/components/UserLink.svelte";

  let {
    stages,
    formatDay,
    aside,
    rules,
  }: {
    stages: EventStage[];
    formatDay: (iso: string) => string;
    /** The evening section: its races, beside the tree's first rows. */
    aside?: Snippet;
    /** The playoff rules card. */
    rules?: Snippet;
  } = $props();

  let layout = $derived(bracketLayout(stages));
  let depth = $derived(layout.rounds.length);
  // A tall tree seats the evening section above the Champion in a side
  // column, narrower from four rounds on so the rounds keep their width; a
  // short one keeps a narrow Champion column, the evening beside it.
  let sideWidth = $derived(
    !layout.tall ? "0.7fr" : depth >= 4 ? "0.8fr" : "1.25fr",
  );
  let columns = $derived(
    `${"minmax(0, 1fr) 24px ".repeat(depth)}minmax(0, ${sideWidth})`,
  );
  // The tall grid gives its first row to the titles.
  let top = $derived(layout.tall ? 2 : 1);
  let side = $derived(2 * depth + 1);
  // Equal tree rows so a first-round box that grows (a wrapped label) does
  // not throw off the connectors' row centres: title row, tree rows, rules
  // row in the tall layout; tree rows, newcomers row in the short one.
  let rowsTemplate = $derived(
    layout.tall
      ? `auto repeat(${layout.rows}, 1fr) auto`
      : `repeat(${layout.rows}, 1fr) auto`,
  );
  // Mobile reading order (tall layout): the evening first, then the rounds.
  let orderOf = $derived(
    new Map(
      layout.rounds.flat().map((cell, i) => [cell.stage.key, 2 + i] as const),
    ),
  );
  let afterTree = $derived(2 + layout.rounds.flat().length);

  const dayOf = (stage: EventStage) =>
    stage.date ? formatDay(stage.date) : DATE_TO_BE_AGREED;

  function stateOf(stage: EventStage): "setup" | "running" | "finished" {
    if (stage.complete) return "finished";
    return stage.races.some((r) => r.race.status === "running")
      ? "running"
      : "setup";
  }
  function signalOf(stage: EventStage): { cls: string; text: string } {
    const state = stateOf(stage);
    if (state === "finished")
      return { cls: "signal-finished", text: "Finished" };
    if (state === "running") return { cls: "signal-running", text: "Live" };
    return { cls: "signal-setup", text: "Upcoming" };
  }
  // One chip per expected race, its mode label (or "Race n" past the modes
  // list) coloured by the attached race's state, so the chips double as the
  // evening's progress.
  function chipsOf(stage: EventStage): StageChip[] {
    return fillSlots(stage.races, stage.races_expected).map((entry, i) => {
      const status = entry?.race.status;
      return {
        text: stage.modes[i] ?? `Race ${i + 1}`,
        state:
          status === "finished"
            ? "done"
            : status === "running"
              ? "live"
              : "todo",
        href: entry ? `/race/${entry.race.id}` : undefined,
        title: entry
          ? stripStagePrefix(entry.race.name, stage.label)
          : undefined,
      };
    });
  }
  function rowsOf(stage: EventStage): StageRow[] {
    if (stage.results.length > 0) {
      return stage.results.map((e, i) => ({
        key: e.user.id,
        rank: i + 1,
        user: e.user,
        newcomer: e.newcomer,
        right: e.advances ? `adv ${e.points}` : String(e.points),
        // Points move while the evening runs (running races score
        // provisionally), so they read brass until the stage is complete.
        rightClass: e.advances
          ? "adv"
          : !stage.complete
            ? "prov"
            : i === 0
              ? "lead"
              : "pts",
      }));
    }
    // A decided slot's label is "Seed N" for a qualifier seed, or the
    // source stage's label (e.g. "Quarter A") when it comes from an earlier
    // playoff stage; only the seed form has a rank number to show, so the
    // stage-provenance form goes in the right cell instead.
    return stage.field.map((slot, i) => {
      const isSeed = slot.label.startsWith("Seed ");
      return {
        key: `${stage.key}-${i}`,
        rank: slot.user && isSeed ? slot.label.replace("Seed ", "") : null,
        user: slot.user,
        label: slot.label,
        right: slot.user && !isSeed ? slot.label : "",
        rightClass: "pts",
      };
    });
  }
</script>

{#snippet box(stage: EventStage)}
  <EventStageBox
    title={stage.label}
    meta={dayOf(stage)}
    state={stateOf(stage)}
    signal={signalOf(stage)}
    rows={rowsOf(stage)}
    chips={chipsOf(stage)}
  />
{/snippet}

{#snippet crown(stage: EventStage, name: string)}
  {@const winner = stageWinner(stage)}
  <div class="champ" class:decided={winner !== null}>
    <div class="route" aria-hidden="true">
      <span class="line"></span><span class="term"></span>
    </div>
    <div class="name">{name}</div>
    {#if winner}
      <div class="who"><UserLink user={winner} showBadge showAvatar /></div>
    {:else}
      <div class="who tbd">
        {stage.date
          ? `Decided ${formatDay(stage.date)}`
          : "Decided in the final"}
      </div>
    {/if}
  </div>
{/snippet}

{#snippet line(path: string)}
  <svg width="24" height="100%" viewBox="0 0 24 100" preserveAspectRatio="none"
    ><path
      d={path}
      fill="none"
      stroke="var(--color-border)"
      stroke-width="2"
      vector-effect="non-scaling-stroke"
    /></svg
  >
{/snippet}

{#snippet tree()}
  <div
    class="brk"
    class:tall={layout.tall}
    style:grid-template-columns={columns}
    style:grid-template-rows={rowsTemplate}
  >
    {#if layout.tall}
      <div
        class="title"
        style:grid-column="1 / {side - 1}"
        style:grid-row="1"
        style:--order="1"
      >
        <SectionTitle>Bracket</SectionTitle>
      </div>
      {#if aside}
        <div
          class="aside"
          style:grid-column={side}
          style:grid-row="1 / {top + layout.rows}"
          style:--order="0"
        >
          {@render aside()}
        </div>
      {/if}
    {/if}
    {#each layout.rounds.flat() as cell (cell.stage.key)}
      <div
        class="cell"
        class:fed={cell.round > 0}
        style:grid-column={2 * cell.round + 1}
        style:grid-row="{top + cell.row} / span {cell.span}"
        style:--order={orderOf.get(cell.stage.key)}
      >
        {@render box(cell.stage)}
      </div>
    {/each}
    {#each layout.links as link (link.target.stage.key)}
      <div
        class="conn"
        aria-hidden="true"
        style:grid-column={2 * link.target.round}
        style:grid-row="{top + link.target.row} / span {link.target.span}"
      >
        {@render line(linkPath(link.from))}
      </div>
    {/each}
    {#if layout.final}
      <div
        class="conn"
        aria-hidden="true"
        style:grid-column={side - 1}
        style:grid-row="{top + layout.final.row} / span {layout.final.span}"
      >
        {@render line("M0 50 H24")}
      </div>
      <div
        class="champ-cell"
        style:grid-column={side}
        style:grid-row="{top + layout.final.row} / span {layout.final.span}"
        style:--order={afterTree}
      >
        {@render crown(layout.final.stage, "Champion")}
      </div>
    {/if}
    {#if layout.newcomers}
      <!-- Tall: under the final, level with the last first-round box. Short:
           a row of its own under the tree. -->
      <div
        class="newcomers"
        style:grid-column="{side - 2} / span 3"
        style:grid-row={layout.tall ? top + layout.rows - 1 : top + layout.rows}
        style:--order={afterTree + 1}
      >
        {@render box(layout.newcomers)}
        <div class="conn" aria-hidden="true">{@render line("M0 50 H24")}</div>
        {@render crown(layout.newcomers, "Newcomers")}
      </div>
    {/if}
    {#if layout.tall && rules}
      <div
        class="rules"
        style:grid-column="1"
        style:grid-row={top + layout.rows}
        style:--order={afterTree + 2}
      >
        {@render rules()}
      </div>
    {/if}
  </div>
{/snippet}

{#if layout.tall}
  {@render tree()}
{:else}
  <div class="split">
    <div>
      <SectionTitle>Bracket</SectionTitle>
      {@render tree()}
    </div>
    {#if aside || rules}
      <div class="stack">
        {#if aside}{@render aside()}{/if}
        {#if rules}{@render rules()}{/if}
      </div>
    {/if}
  </div>
{/if}

<style>
  .brk {
    display: grid;
    column-gap: 0;
    row-gap: 14px;
    align-items: stretch;
  }
  .brk > * {
    min-width: 0;
  }
  .aside {
    align-self: start;
  }
  .cell.fed,
  .champ-cell {
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  /* A first-round cell's box fills its row (now an equal tree row), instead
   * of keeping its own content height, so a wrapped label in one box does
   * not throw the connectors' row centres off for the others. */
  .cell:not(.fed) {
    display: grid;
  }
  /* The newcomers' final, its connector and its crown share the final's,
   * the gutter's and the side column's tracks, bottom-aligned together. */
  .newcomers {
    display: grid;
    grid-template-columns: subgrid;
    align-items: center;
    align-self: end;
  }
  .conn {
    display: flex;
    align-items: stretch;
  }
  .conn svg {
    display: block;
  }
  .split {
    display: grid;
    grid-template-columns: minmax(0, 8fr) minmax(0, 4fr);
    gap: 24px;
    align-items: start;
  }
  .stack {
    display: flex;
    flex-direction: column;
    gap: 2rem;
    min-width: 0;
  }
  .champ {
    position: relative;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    padding: 0.7rem 0.9rem 0.75rem;
    /* A floor, not a fixed height: a two-line placeholder grows the box
     * instead of overflowing past the padding. */
    min-height: 74px;
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    justify-content: center;
  }
  .champ .route {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
    height: 14px;
    pointer-events: none;
  }
  .champ .route .line {
    position: absolute;
    /* No start ring here: the line runs from the card edge */
    left: 10px;
    right: 14px;
    top: 6px;
    border-top: 2px dashed var(--color-text-disabled);
  }
  .champ .route .term {
    position: absolute;
    right: 6px;
    top: 0;
    width: 14px;
    height: 14px;
    background: var(--color-text-disabled);
  }
  .champ.decided .route .line {
    border-top: 2px solid var(--color-gold);
  }
  .champ.decided .route .term {
    background: var(--color-gold);
  }
  .champ .name {
    font-family: var(--font-display);
    font-size: 1.05rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
    color: var(--color-gold);
  }
  .champ .who {
    margin-top: 0.15rem;
    font-weight: 600;
  }
  .champ .who.tbd {
    color: var(--color-text-disabled);
    font-style: italic;
    font-weight: 400;
    font-size: var(--font-size-sm);
  }
  /* Tall tree: one column, the evening first, the rounds in order. */
  @media (max-width: 899px) {
    .brk.tall,
    .brk.tall .newcomers {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .brk.tall > * {
      order: var(--order, 0);
      align-self: stretch;
    }
    .brk.tall .newcomers {
      align-items: stretch;
    }
    .brk.tall .conn {
      display: none;
    }
    .split {
      grid-template-columns: 1fr;
    }
  }
  /* Short tree: stacks as before, in document order. */
  @media (max-width: 760px) {
    .brk,
    .newcomers {
      display: flex;
      flex-direction: column;
      gap: 14px;
    }
    .newcomers {
      align-self: stretch;
      align-items: stretch;
    }
    .conn {
      display: none;
    }
  }
</style>
