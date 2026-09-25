<script lang="ts">
  import type { UserProfile } from "$lib/api";
  import { sceneLayout } from "$lib/cast/layout";
  import {
    fillSlots,
    formatEventDay,
    formatEventTime,
    DATE_TO_BE_AGREED,
  } from "$lib/events";
  import CastPlate from "$lib/components/cast/CastPlate.svelte";
  import CastDesk from "$lib/components/cast/CastDesk.svelte";
  import CastRaceCard from "$lib/components/cast/CastRaceCard.svelte";
  import CastRoundStandings from "$lib/components/cast/CastRoundStandings.svelte";

  let { data } = $props();
  let params = $derived(data.castParams);
  let stage = $derived(data.stage);
  let layout = $derived(sceneLayout("talk", { cams: params.cams }));

  // Rendered in the viewer's own timezone, like every other date on the
  // site: no explicit timeZone is passed to these, same as formatEventDay
  // and formatEventTime's other callers.
  let dateText = $derived(
    stage.date
      ? `${formatEventDay(stage.date)} · ${formatEventTime(stage.date)}`
      : DATE_TO_BE_AGREED,
  );

  function casterLabel(profile: UserProfile | null): string | null {
    return profile
      ? profile.twitch_display_name || profile.twitch_username
      : null;
  }
  // A username that didn't resolve to a real user (typo, wrong URL) leaves
  // that cam unnamed rather than failing the whole scene.
  let casterNames = $derived<[string | null, string | null]>([
    casterLabel(data.casters[0] ?? null),
    casterLabel(data.casters[1] ?? null),
  ]);

  // fillSlots keeps a stage slot with no race yet in its place as null, the
  // same shape the event page itself renders (see EventRacePlaceholder).
  let slots = $derived(fillSlots(stage.races, stage.races_expected));
</script>

<CastPlate scene="talk" cams={params.cams} guides={params.guides}>
  <div
    class="topline"
    style="left: {layout.panels.topline.x}px; top: {layout.panels.topline
      .y}px; width: {layout.panels.topline.w}px; height: {layout.panels.topline
      .h}px;"
  >
    <span class="tl-left">{stage.label} &middot; Playoff night</span>
    <span class="tl-right">{dateText}</span>
  </div>

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
    racesPlayed={stage.races.length}
    racesExpected={stage.races_expected}
    results={stage.results}
  />

  <CastDesk
    scene="talk"
    cams={params.cams}
    casters={casterNames}
    partnerName={data.event.partner_name}
  />
</CastPlate>

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
