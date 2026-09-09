<script lang="ts">
  import type { EventQualified, EventStage } from "$lib/api";
  import EventStageBox, { type StageRow } from "./EventStageBox.svelte";

  let {
    qualified,
    stages,
    cutAt,
    formatDate,
  }: {
    qualified: EventQualified;
    stages: EventStage[];
    cutAt: string;
    formatDate: (iso: string) => string;
  } = $props();

  const letters = ["A", "B", "C", "D"];
  let boxes = $derived(
    qualified.groups.map((group) => {
      const stage = stages.find((s) => s.key === group.stage_key);
      const semiIndex = stages
        .filter((s) => s.kind === "semi")
        .findIndex((s) => s.key === group.stage_key);
      const title =
        stage?.kind === "newcomers"
          ? "Newcomers"
          : `Group ${letters[semiIndex] ?? ""}`;
      const meta = stage
        ? `${stage.label} · ${formatDate(stage.date)}`
        : group.label;
      const rows: StageRow[] = group.entries.map((e, i) => ({
        key: `${group.stage_key}-${i}`,
        rank: e.seed,
        user: e.user,
        newcomer: e.newcomer,
        label: e.note ?? "open",
      }));
      const filled = group.entries.filter((e) => e.user).length;
      return {
        key: group.stage_key,
        title,
        meta,
        rows,
        signal: {
          cls: "signal-setup",
          text: `${filled} / ${group.entries.length}`,
        },
      };
    }),
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
    {qualified.provisional
      ? `as the ladder stands; final at the cut, ${formatDate(cutAt)}`
      : "decided at the cut"}
  </p>
  {#each boxes as box (box.key)}
    <EventStageBox
      title={box.title}
      meta={box.meta}
      state="setup"
      signal={box.signal}
      rows={box.rows}
    />
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
</style>
