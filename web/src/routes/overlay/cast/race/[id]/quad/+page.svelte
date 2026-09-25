<script lang="ts">
  import { raceStore } from "$lib/stores/race.svelte";
  import { sceneLayout, quadSeat } from "$lib/cast/layout";
  import { resolveSlots } from "$lib/cast/params";
  import { parseDagGraph } from "$lib/dag";
  import CastPlate from "$lib/components/cast/CastPlate.svelte";
  import CastDesk from "$lib/components/cast/CastDesk.svelte";
  import CastPov from "$lib/components/cast/CastPov.svelte";
  import RunnerCard from "$lib/components/cast/RunnerCard.svelte";

  let { data } = $props();
  let params = $derived(data.castParams);
  let layout = $derived(sceneLayout("quad", { cams: params.cams }));

  // Live rows, seated in the order the URL asked for.
  let seated = $derived(resolveSlots(raceStore.leaderboard, params.slots));
  // Which POV holes actually hold a runner right now, for CastPlate: a
  // field smaller than four should not pierce a hole nobody sits in.
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
  // same nodeNames pattern the metro scene's log builds.
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
</script>

<CastPlate scene="quad" cams={params.cams} guides={params.guides} {seatedSlots}>
  {#each seated as participant, i (i)}
    {@const slot = i + 1}
    {@const hole = layout.holes.find((h) => h.id === `pov${slot}`)!}
    <CastPov rect={hole} {participant} {slot} nameplate={false} />
    {#if participant}
      <RunnerCard
        {participant}
        rank={ranks.get(participant.id) ?? slot}
        avatarUrl={avatars.get(participant.id) ?? null}
        {totalLayers}
        {zoneNames}
        rect={quadSeat(slot).card}
        variant={quadSeat(slot).mirrored ? "mirror" : "card"}
        leader={ranks.get(participant.id) === 1}
      />
    {/if}
  {/each}
  <CastDesk
    scene="quad"
    race={data.race}
    cams={params.cams}
    casters={params.casters}
    partnerName={data.partnerName}
  />
</CastPlate>
