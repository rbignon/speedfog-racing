<script lang="ts">
  import type { EventStage } from "$lib/api";
  import { liveZoneTitle, type LiveMatch } from "$lib/events";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
  import EventMatchPanel from "./EventMatchPanel.svelte";

  /**
   * The matches on air at the top of the event page, every bracket's: one
   * panel each, two a row; a lone match takes the full width.
   */
  let {
    matches,
    stages,
    languages = {},
    now,
  }: {
    matches: LiveMatch[];
    stages: EventStage[];
    languages?: Record<string, string>;
    now: Date;
  } = $props();
</script>

<section>
  <SectionTitle>{liveZoneTitle(matches)}</SectionTitle>
  <div class="grid" class:single={matches.length === 1}>
    {#each matches as match (match.stage.key)}
      <EventMatchPanel
        {match}
        {stages}
        {languages}
        {now}
        wide={matches.length === 1}
      />
    {/each}
  </div>
</section>

<style>
  .grid {
    display: grid;
    grid-template-columns: repeat(2, minmax(0, 1fr));
    gap: 24px;
    align-items: start;
  }
  .grid.single {
    grid-template-columns: minmax(0, 1fr);
  }
  @media (max-width: 899px) {
    .grid {
      grid-template-columns: minmax(0, 1fr);
    }
  }
</style>
