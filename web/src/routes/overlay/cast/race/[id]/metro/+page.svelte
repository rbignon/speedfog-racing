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

  // maxLayers=13 at this box's 1888x482 aspect gives roughly the 1.5x zoom
  // the spec measured, where zone labels render near 17px instead of the
  // strip's under-7px. Both stay overridable from the URL for a seed that
  // needs more or less room, the same maxLayers/fontSize pattern
  // /overlay/race/[id]/dag already reads.
  const DEFAULT_MAX_LAYERS = 13;
  const DEFAULT_LABEL_FONT_SIZE = 11;
  let maxLayers = $derived(
    (() => {
      const raw = page.url.searchParams.get("maxLayers");
      if (raw === null || raw === "") return DEFAULT_MAX_LAYERS;
      const n = parseInt(raw, 10);
      return isNaN(n) || n < 3 ? DEFAULT_MAX_LAYERS : n;
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

  // 6 rows is what the log panel's 230px height fits under its ~32px title
  // (blk-title + its margin): 230 - 32 = 198, / 31px per row = 6.38.
  const LOG_LIMIT = 6;
  let logRows = $derived(
    buildCastLog(raceStore.leaderboard, nodeNames, LOG_LIMIT),
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
        showPlayerLabels
        showLabels
        labelMaxChars={26}
        containerAspect={mapRect.w / mapRect.h}
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
