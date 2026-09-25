<script lang="ts">
  import { raceStore } from "$lib/stores/race.svelte";
  import { sceneLayout } from "$lib/cast/layout";
  import { resolveSlots } from "$lib/cast/params";
  import { parseDagGraph } from "$lib/dag";
  import { buildCastSplits } from "$lib/cast/splits";
  import CastPlate from "$lib/components/cast/CastPlate.svelte";
  import CastDesk from "$lib/components/cast/CastDesk.svelte";
  import CastPov from "$lib/components/cast/CastPov.svelte";
  import RunnerCard from "$lib/components/cast/RunnerCard.svelte";
  import CastMiniStandings from "$lib/components/cast/CastMiniStandings.svelte";

  let { data } = $props();
  let params = $derived(data.castParams);
  let layout = $derived(
    sceneLayout("focus", { focus: params.focus, cams: params.cams }),
  );

  // Live rows, seated in the order the URL asked for.
  let seated = $derived(resolveSlots(raceStore.leaderboard, params.slots));
  // Which POV/hero holes actually hold a runner right now, for CastPlate: a
  // field smaller than four should not pierce a hole nobody sits in,
  // including when the hero slot itself is empty.
  let seatedSlots = $derived(seated.flatMap((p, i) => (p ? [i + 1] : [])));
  let ranks = $derived(
    new Map(raceStore.leaderboard.map((p, i) => [p.id, i + 1])),
  );
  let avatars = $derived(
    new Map(
      data.race.participants.map((p) => [p.id, p.user.twitch_avatar_url]),
    ),
  );
  let totalLayers = $derived(
    raceStore.seed?.total_layers ?? data.race.seed_total_layers,
  );

  // WsParticipant.current_zone is a graph node id, never a display string
  // (see RunnerCard's zoneLabel): resolve it from the seed's own graph, the
  // same nodeNames pattern the quad scene builds and buildCastSplits reuses.
  let zoneNames = $derived(
    new Map(
      raceStore.seed?.graph_json
        ? parseDagGraph(raceStore.seed.graph_json).nodes.map((n) => [
            n.id,
            n.displayName,
          ])
        : [],
    ),
  );

  // The hero hole is the one the geometry marked "hero"; every other hole
  // here is a small "pov". Its slot number comes out of the hole's own id
  // (`pov${n}`), the same shape every hole in this module uses.
  let heroHole = $derived(layout.holes.find((h) => h.role === "hero")!);
  let heroSlot = $derived(Number(heroHole.id.slice(3)));
  let heroParticipant = $derived(seated[heroSlot - 1]);
  let heroSplits = $derived(
    buildCastSplits(heroParticipant?.zone_history ?? null, zoneNames),
  );
</script>

<CastPlate
  scene="focus"
  focus={params.focus}
  cams={params.cams}
  guides={params.guides}
  {seatedSlots}
>
  {#each seated as participant, i (i)}
    {@const slot = i + 1}
    {@const hole = layout.holes.find((h) => h.id === `pov${slot}`)!}
    <CastPov
      rect={hole}
      {participant}
      {slot}
      nameplate={hole.role !== "hero"}
    />
  {/each}
  {#if heroParticipant}
    <RunnerCard
      participant={heroParticipant}
      rank={ranks.get(heroParticipant.id) ?? heroSlot}
      avatarUrl={avatars.get(heroParticipant.id) ?? null}
      {totalLayers}
      {zoneNames}
      rect={layout.panels.focus}
      variant="tall"
      leader={ranks.get(heroParticipant.id) === 1}
      splits={heroSplits}
    />
  {/if}
  <CastMiniStandings
    participants={raceStore.leaderboard}
    {totalLayers}
    rect={layout.panels.standings}
  />
  <CastDesk
    scene="focus"
    race={data.race}
    cams={params.cams}
    casters={params.casters}
    partnerName={data.partnerName}
  />
</CastPlate>
