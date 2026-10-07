<script lang="ts">
  import type {
    EventBracket,
    EventQualified,
    EventQualifiedGroup,
    EventStage,
  } from "$lib/api";
  import { bracketStages, qualifiedMeta, qualifiedSections } from "$lib/events";
  import EventStageBox, { type StageRow } from "./EventStageBox.svelte";

  let {
    qualified,
    stages,
    brackets,
    cutAt,
    formatDate,
  }: {
    qualified: EventQualified;
    stages: EventStage[];
    brackets: EventBracket[];
    cutAt: string;
    formatDate: (iso: string) => string;
  } = $props();

  function boxOf(group: EventQualifiedGroup) {
    const stage = stages.find((s) => s.key === group.stage_key);
    const rows: StageRow[] = group.entries.map((e, i) => ({
      key: `${group.stage_key}-${i}`,
      rank: e.seed,
      user: e.user,
      newcomer: e.newcomer,
      label: e.note ?? undefined,
    }));
    const filled = group.entries.filter((e) => e.user).length;
    return {
      key: group.stage_key,
      title: group.label,
      meta: stage
        ? qualifiedMeta(
            stage,
            bracketStages(stages, stage.bracket ?? ""),
            formatDate,
          )
        : "",
      chips: (stage?.modes ?? []).map((text) => ({
        text,
        state: "todo" as const,
      })),
      rows,
      signal: {
        cls: "signal-setup",
        text: `${filled} / ${group.entries.length}`,
      },
    };
  }

  let sections = $derived(
    qualifiedSections(qualified, stages, brackets).map((section) => ({
      ...section,
      boxes: section.groups.map(boxOf),
    })),
  );
</script>

<div class="qualified">
  <p class="note">
    <span
      class="signal {qualified.provisional
        ? 'signal-active'
        : 'signal-finished'}"
      >{qualified.provisional ? "Provisional" : "Final"}</span
    >
    <span class="fact cut"
      ><span class="k">Cut</span><span class="v">{formatDate(cutAt)}</span
      ></span
    >
  </p>
  {#each sections as section (section.key)}
    {#if section.label}<p class="bracket-label">{section.label}</p>{/if}
    {#each section.boxes as box (box.key)}
      <EventStageBox
        title={box.title}
        meta={box.meta}
        state="setup"
        signal={box.signal}
        rows={box.rows}
        chips={box.chips}
      />
    {/each}
  {/each}
</div>

<style>
  .qualified {
    display: flex;
    flex-direction: column;
    gap: 14px;
  }
  .note {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    margin: 0;
    display: flex;
    gap: 0.5rem;
    align-items: center;
    flex-wrap: wrap;
  }
  .bracket-label {
    margin: 0.4rem 0 0;
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }
  .cut {
    margin-left: auto;
  }
</style>
