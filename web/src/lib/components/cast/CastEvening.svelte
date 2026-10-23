<script lang="ts">
  import { onMount, type Snippet } from "svelte";
  import {
    fetchEvent,
    type EventDetail,
    type EventShowcase,
    type EventStage,
  } from "$lib/api";
  import { sceneLayout, type SlateSceneId } from "$lib/cast/layout";
  import {
    fillSlots,
    formatEventDay,
    formatEventTime,
    nextStageLabels,
    DATE_TO_BE_AGREED,
  } from "$lib/events";
  import CastRaceCard from "./CastRaceCard.svelte";
  import CastRoundStandings from "./CastRoundStandings.svelte";

  type AnyStage = EventStage | EventShowcase;

  interface Props {
    /** Talk or a slate: they draw these panels at the same place. */
    scene: "talk" | SlateSceneId;
    event: Pick<EventDetail, "slug" | "stages">;
    /** The stage as loaded; the poll below swaps in each fresher copy. */
    stage: AnyStage;
    /** What the scene draws above the evening row, from that same fresh
     * stage, and the stage each advancing place goes on to. */
    children?: Snippet<[AnyStage, (string | null)[]]>;
  }

  let { scene, event, stage: loaded, children }: Props = $props();

  // Writable $derived, like the event page's detail: starts from the loaded
  // stage and takes each poll's fresher copy below.
  let stage: AnyStage = $derived(loaded);
  let layout = $derived(sceneLayout(scene));
  // A showcase is no playoff round: its label stands alone.
  let toplineLabel = $derived(
    stage.kind === "showcase" ? stage.label : `${stage.label} · Playoff`,
  );

  // Rendered in the viewer's own timezone, like every other date on the
  // site: no explicit timeZone is passed to these, same as formatEventDay
  // and formatEventTime's other callers. A day whose time is not set yet
  // shows alone.
  let dateText = $derived(
    !stage.date
      ? DATE_TO_BE_AGREED
      : stage.time_set
        ? `${formatEventDay(stage.date)} · ${formatEventTime(stage.date)}`
        : formatEventDay(stage.date),
  );

  // The stage each advancing place goes on to, named on its chip: the one
  // whose seat takes that place. A final or a showcase feeds none.
  let nextLabels = $derived(
    nextStageLabels(event.stages, stage.key, stage.advance),
  );

  // fillSlots keeps a stage slot with no race yet in its place as null, the
  // shape the event page's match tables and Up next chips render too.
  let slots = $derived(fillSlots(stage.races, stage.races_expected));

  // The scene stays up in OBS all evening and holds no WebSocket: re-read
  // the event so the race cards and the standings follow the races without
  // the caster reloading the source.
  const POLL_MS = 30_000;
  onMount(() => {
    const poll = setInterval(async () => {
      const slug = event.slug;
      const key = stage.key;
      try {
        const fresh = await fetchEvent(slug);
        const next = [...fresh.stages, ...fresh.showcases].find(
          (s) => s.key === key,
        );
        if (next) stage = next;
      } catch {
        /* keep the last good state; the next tick retries */
      }
    }, POLL_MS);
    return () => clearInterval(poll);
  });
</script>

<div
  class="topline"
  style="left: {layout.panels.topline.x}px; top: {layout.panels.topline
    .y}px; width: {layout.panels.topline.w}px; height: {layout.panels.topline
    .h}px;"
>
  <span class="tl-left">{toplineLabel}</span>
  <span class="tl-right">{dateText}</span>
</div>

{@render children?.(stage, nextLabels)}

{#each slots as entry, i (i)}
  <CastRaceCard
    rect={layout.panels[`race${i + 1}`]}
    slot={i + 1}
    mode={stage.modes[i]}
    {entry}
    field={stage.field}
  />
{/each}

<div
  class="sep"
  style="left: {layout.panels.separator.x}px; top: {layout.panels.separator
    .y}px; width: {layout.panels.separator.w}px; height: {layout.panels
    .separator.h}px;"
></div>

<CastRoundStandings
  rect={layout.panels.standings}
  label={stage.label}
  results={stage.settled_results}
  {nextLabels}
  advance={stage.advance}
  complete={stage.complete}
/>

<style>
  .topline {
    position: absolute;
    display: flex;
    align-items: center;
    justify-content: space-between;
    font-family: var(--font-display);
    font-size: 28px;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  .tl-right {
    font-family: var(--font-mono);
    font-size: 20px;
    letter-spacing: 0.04em;
    text-transform: none;
  }

  .sep {
    position: absolute;
    background: var(--color-border);
  }
</style>
