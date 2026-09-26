<script lang="ts">
  import { page } from "$app/state";
  import { raceStore } from "$lib/stores/race.svelte";
  import { sceneLayout } from "$lib/cast/layout";
  import { parseDagGraph, MetroDagFull } from "$lib/dag";
  import { buildCastLog } from "$lib/cast/log";
  import CastPlate from "$lib/components/cast/CastPlate.svelte";
  import CastDesk from "$lib/components/cast/CastDesk.svelte";
  import CastLog from "$lib/components/cast/CastLog.svelte";
  import CastStandings from "$lib/components/cast/CastStandings.svelte";

  let { data } = $props();
  let params = $derived(data.castParams);
  let layout = $derived(sceneLayout("metro", { cams: params.cams }));

  // The map is listed as a hole only so the guides mode can print its box
  // (see layout.ts's metroScene comment): CastPlate never pierces it, this
  // page draws the map itself, inside that same rectangle.
  let mapRect = $derived(layout.holes.find((h) => h.id === "map")!);

  let raceStatus = $derived(raceStore.race?.status ?? data.race.status);
  let totalLayers = $derived(
    raceStore.seed?.total_layers ?? data.race.seed_total_layers,
  );

  // WsParticipant.current_zone (and zone_history's node_id) are graph node
  // ids, never display strings: resolve them through the seed's own graph,
  // the same nodeNames pattern the quad and focus scenes build.
  let nodeNames = $derived(
    new Map(
      raceStore.seed?.graph_json
        ? parseDagGraph(raceStore.seed.graph_json).nodes.map((n) => [
            n.id,
            n.displayName,
          ])
        : [],
    ),
  );

  // The map shows the whole seed by default, its rows spread apart to fill
  // the box, so a viewer sees at a glance how far into the race each runner
  // is; zone names are left out, since at that zoom they would render at a
  // few pixels (the standings below carry each runner's zone). Runner marks
  // keep their on-screen size whatever the zoom (MetroDagFull's
  // `keepMarkSize`).
  //
  // `maxLayers=N` in the URL follows the runners instead, with a window N
  // layers wide, and brings the zone names back; `labels=0|1` overrides
  // that choice either way and `fontSize` sets their size, the same knobs
  // /overlay/race/[id]/dag reads. 9 graph units renders near 13px at a
  // 13-layer window: 11 made a 90-node seed illegible, 7 read thin at
  // broadcast distance.
  const DEFAULT_LABEL_FONT_SIZE = 9;
  let followLayers = $derived(
    (() => {
      const raw = page.url.searchParams.get("maxLayers");
      if (raw === null || raw === "") return null;
      const n = parseInt(raw, 10);
      return isNaN(n) || n < 3 ? null : n;
    })(),
  );
  let wholeMap = $derived(followLayers === null);
  let showZoneLabels = $derived(
    (() => {
      const raw = page.url.searchParams.get("labels");
      if (raw === "0") return false;
      if (raw === "1") return true;
      return !wholeMap;
    })(),
  );
  let labelFontSize = $derived(
    (() => {
      const raw = page.url.searchParams.get("fontSize");
      if (raw === null || raw === "") return DEFAULT_LABEL_FONT_SIZE;
      const n = parseInt(raw, 10);
      return isNaN(n) || n < 6 || n > 32 ? DEFAULT_LABEL_FONT_SIZE : n;
    })(),
  );
  // More layers than any seed has: the follow viewport clamps its window to
  // the graph, so this shows it whole.
  const WHOLE_MAP_LAYERS = 1000;
  let maxLayers = $derived(followLayers ?? WHOLE_MAP_LAYERS);

  // 6 rows is what the log panel's 230px height fits under its ~32px title
  // (blk-title + its margin): 230 - 32 = 198, / 31px per row = 6.38.
  const LOG_LIMIT = 6;
  let logRows = $derived(
    buildCastLog(raceStore.leaderboard, nodeNames, LOG_LIMIT),
  );

  // Caster override for how many standings rows to show, same name and
  // spirit as /overlay/race/[id]/leaderboard's own `lines`: default fits as
  // many as the panel allows, an explicit empty value keeps that same
  // default (there is no "unlimited" here, the panel is a fixed box, not an
  // OBS widget the caster sizes themselves), and a positive integer asks
  // for that many, still capped to what CastStandings' own rect fits.
  let lines = $derived(
    (() => {
      const raw = page.url.searchParams.get("lines");
      if (raw === null || raw === "") return null;
      const n = parseInt(raw, 10);
      return isNaN(n) || n <= 0 ? null : n;
    })(),
  );
</script>

<CastPlate scene="metro" cams={params.cams} guides={params.guides}>
  <div
    class="map"
    style="left: {mapRect.x}px; top: {mapRect.y}px; width: {mapRect.w}px; height: {mapRect.h}px;"
  >
    {#if raceStore.seed?.graph_json}
      <MetroDagFull
        graphJson={raceStore.seed.graph_json}
        participants={raceStore.leaderboard}
        {raceStatus}
        transparent
        follow
        showLiveDots
        playerTags
        showLabels={showZoneLabels}
        labelMaxChars={26}
        containerAspect={mapRect.w / mapRect.h}
        fillContainer={wholeMap}
        keepMarkSize
        {maxLayers}
        {labelFontSize}
      />
    {/if}
  </div>
  <CastLog rows={logRows} rect={layout.panels.log} />
  <CastStandings
    participants={raceStore.leaderboard}
    {totalLayers}
    zoneNames={nodeNames}
    rect={layout.panels.standings}
    {lines}
  />
  <CastDesk
    scene="metro"
    race={data.race}
    cams={params.cams}
    casters={params.casters}
    partnerName={data.partnerName}
  />
</CastPlate>

<style>
  /* A plain block of the rect's own width and height, not a centring flex
   * box: FollowViewport's inner svg is `width: 100%`, and a flex child's
   * percentage width resolves against its content rather than the
   * container unless something makes it grow, which nothing here does. As
   * a block child its 100% resolves against this element's own definite
   * width (from mapRect, the same rectangle layout.ts gives every other
   * coordinate in this scene), which is what lets the svg's own aspect
   * (fitted to containerAspect) land on this box's actual size instead of
   * FollowViewport's `min-width: 600px` winning by default.
   */
  .map {
    position: absolute;
  }
</style>
