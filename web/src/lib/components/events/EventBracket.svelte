<script lang="ts">
  import type { EventStage } from "$lib/api";
  import EventStageBox, { type StageRow } from "./EventStageBox.svelte";
  import UserLink from "$lib/components/UserLink.svelte";

  let {
    stages,
    formatDate,
    formatDay,
  }: {
    stages: EventStage[];
    formatDate: (iso: string) => string;
    formatDay: (iso: string) => string;
  } = $props();

  let semis = $derived(stages.filter((s) => s.kind === "semi"));
  let final = $derived(stages.find((s) => s.kind === "final") ?? null);
  let newcomers = $derived(stages.find((s) => s.kind === "newcomers") ?? null);

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
  function metaOf(stage: EventStage): string {
    const played = stage.races.filter(
      (r) => r.race.status === "finished",
    ).length;
    const progress = stage.complete
      ? `${stage.races_expected} races`
      : played > 0
        ? `race ${Math.min(played + 1, stage.races_expected)} of ${stage.races_expected}`
        : `${stage.races_expected} races`;
    return `${formatDay(stage.date)} · ${progress}`;
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
    // source stage's label (e.g. "Semi A") when it comes from an earlier
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
  function winnerOf(stage: EventStage | null) {
    return stage && stage.complete ? (stage.results[0]?.user ?? null) : null;
  }
  let modesLine = $derived(
    stages
      .filter((s) => s.modes.length > 0)
      .map((s) => `${s.label}: ${s.modes.join(", ")}`)
      .join(" · "),
  );
</script>

<div class="brk">
  <div class="col">
    {#each semis as stage (stage.key)}
      <EventStageBox
        title={stage.label}
        meta={metaOf(stage)}
        state={stateOf(stage)}
        signal={signalOf(stage)}
        rows={rowsOf(stage)}
      />
    {/each}
  </div>
  <div class="conn" aria-hidden="true">
    <svg
      width="24"
      height="100%"
      viewBox="0 0 24 350"
      preserveAspectRatio="none"
      ><path
        d="M0 84 H12 V266 H0 M12 175 H24"
        fill="none"
        stroke="var(--color-border)"
        stroke-width="2"
      /></svg
    >
  </div>
  <div class="col centre">
    {#if final}
      <EventStageBox
        title={final.label}
        meta={metaOf(final)}
        state={stateOf(final)}
        signal={signalOf(final)}
        rows={rowsOf(final)}
      />
    {/if}
  </div>
  <div class="conn one" aria-hidden="true">
    <svg
      width="24"
      height="100%"
      viewBox="0 0 24 168"
      preserveAspectRatio="none"
      ><path
        d="M0 84 H24"
        fill="none"
        stroke="var(--color-border)"
        stroke-width="2"
      /></svg
    >
  </div>
  <div class="col centre">
    {#if final}
      {@const winner = winnerOf(final)}
      <div class="champ" class:decided={winner !== null}>
        <div class="route" aria-hidden="true">
          <span class="line"></span><span class="term"></span>
        </div>
        <div class="name">Champion</div>
        {#if winner}
          <div class="who"><UserLink user={winner} showBadge showAvatar /></div>
        {:else}
          <div class="who tbd">Decided {formatDate(final.date)}</div>
        {/if}
      </div>
    {/if}
  </div>

  {#if newcomers}
    {@const winner = winnerOf(newcomers)}
    <div class="col indent row2">
      <EventStageBox
        title={newcomers.label}
        meta={metaOf(newcomers)}
        state={stateOf(newcomers)}
        signal={signalOf(newcomers)}
        rows={rowsOf(newcomers)}
      />
    </div>
    <div class="conn one row2" aria-hidden="true">
      <svg
        width="24"
        height="100%"
        viewBox="0 0 24 168"
        preserveAspectRatio="none"
        ><path
          d="M0 84 H24"
          fill="none"
          stroke="var(--color-border)"
          stroke-width="2"
        /></svg
      >
    </div>
    <div class="col centre row2 col-5">
      <div class="champ" class:decided={winner !== null}>
        <div class="route" aria-hidden="true">
          <span class="line"></span><span class="term"></span>
        </div>
        <div class="name">Newcomers</div>
        {#if winner}
          <div class="who"><UserLink user={winner} showBadge showAvatar /></div>
        {:else}
          <div class="who tbd">Decided {formatDate(newcomers.date)}</div>
        {/if}
      </div>
    </div>
  {/if}
</div>
{#if modesLine}<p class="modes">{modesLine}</p>{/if}

<style>
  .brk {
    display: grid;
    grid-template-columns: minmax(0, 1fr) 24px minmax(0, 1fr) 24px minmax(
        0,
        0.7fr
      );
    grid-template-rows: auto;
    column-gap: 0;
    row-gap: 14px;
    align-items: stretch;
  }
  .col {
    display: flex;
    flex-direction: column;
    gap: 14px;
    min-width: 0;
  }
  /* The semis column is always the bracket's first child; splitting it
   * into two equal grid rows (rather than a flex column) is what makes
   * both semi boxes stretch to match each other's height. */
  .brk > .col:first-child {
    display: grid;
    grid-template-rows: 1fr 1fr;
    row-gap: 14px;
  }
  .col.centre {
    justify-content: center;
  }
  .row2 {
    grid-row: 2;
  }
  .col.indent {
    grid-column: 3;
    margin-left: 22px;
  }
  .conn {
    display: flex;
    align-items: center;
  }
  .conn.one.row2 {
    grid-column: 4;
  }
  .col-5 {
    grid-column: 5;
  }
  .conn svg {
    display: block;
  }
  .champ {
    position: relative;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    padding: 0.7rem 0.9rem 0.75rem;
    height: 74px;
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
    left: 14px;
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
  .modes {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    margin: 0.9rem 0 0;
  }
  @media (max-width: 760px) {
    .brk {
      display: flex;
      flex-direction: column;
    }
    .conn {
      display: none;
    }
    .col.indent {
      margin-left: 0;
    }
  }
</style>
