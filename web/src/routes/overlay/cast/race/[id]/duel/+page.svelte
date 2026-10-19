<script lang="ts">
  import { onMount } from "svelte";
  import { raceStore } from "$lib/stores/race.svelte";
  import { sceneStatus } from "$lib/cast/scene-status.svelte";
  import { sceneLayout } from "$lib/cast/layout";
  import { resolveSlots } from "$lib/cast/params";
  import { parseDagGraph } from "$lib/dag";
  import { formatCombo } from "$lib/weapons";
  import {
    getWeaponName,
    isCatalogueReady,
    loadCatalogue,
  } from "$lib/stores/weaponsCatalogue.svelte";
  import CastPlate from "$lib/components/cast/CastPlate.svelte";
  import CastDesk from "$lib/components/cast/CastDesk.svelte";
  import CastPov from "$lib/components/cast/CastPov.svelte";
  import CastDuelCard from "$lib/components/cast/CastDuelCard.svelte";
  import CastDuelVersus from "$lib/components/cast/CastDuelVersus.svelte";

  let { data } = $props();
  let params = $derived(data.castParams);
  let layout = $derived(sceneLayout("duel", { cams: params.cams }));

  // Live rows, seated in the order the URL asked for; the duel only has
  // two holes, so only p1/p2 are read and a p3/p4 in the URL is silently
  // ignored (not fed to resolveSlots, where it would still claim a runner
  // away from the auto-fill pool), the same way metro ignores seating.
  let seated = $derived(
    resolveSlots(raceStore.leaderboard, params.slots.slice(0, 2)).slice(0, 2),
  );
  // Which POV holes actually hold a runner right now, for CastPlate: a
  // one-runner field should not pierce a hole nobody sits in.
  let seatedSlots = $derived(seated.flatMap((p, i) => (p ? [i + 1] : [])));
  let ranks = $derived(
    new Map(raceStore.leaderboard.map((p, i) => [p.id, i + 1])),
  );
  // "setup" until the start countdown is over: see sceneStatus.
  const shownStatus = sceneStatus(() => ({
    status: raceStore.race?.status ?? data.race.status,
    startedAt: raceStore.race?.started_at ?? data.race.started_at,
    delayMs: params.delayMs,
  }));
  let raceStatus = $derived(shownStatus.current);
  let avatars = $derived(
    new Map(
      data.race.participants.map((p) => [p.id, p.user.twitch_avatar_url]),
    ),
  );
  let totalLayers = $derived(
    raceStore.seed?.total_layers ?? data.race.seed_total_layers,
  );

  // WsParticipant.current_zone is a graph node id, never a display string
  // (see CastDuelCard's zoneLabel): resolve it from the seed's own graph,
  // the same nodeNames pattern the quad scene builds.
  let zoneNames = $derived(
    new Map(
      raceStore.seed?.graph_json
        ? parseDagGraph(raceStore.seed.graph_json).nodes.map((n) => [
            n.id,
            n.labelName,
          ])
        : [],
    ),
  );

  // The wielded combo resolves to names only once the catalogue is in, so
  // a card never prints the raw "Weapon #..." fallback mid-load; an OBS
  // scene stays up for hours, so a failed load retries instead of
  // silencing the line for the whole broadcast.
  let catalogueReady = $state(false);
  onMount(() => {
    let timer: ReturnType<typeof setTimeout> | null = null;
    const attempt = () => {
      loadCatalogue()
        .catch(() => {})
        .then(() => {
          if (isCatalogueReady()) catalogueReady = true;
          else timer = setTimeout(attempt, 30_000);
        });
    };
    attempt();
    return () => {
      if (timer) clearTimeout(timer);
    };
  });

  function weaponsOf(participantId: string): string {
    if (!catalogueReady) return "";
    const ids = raceStore.currentWeapons[participantId];
    return ids ? formatCombo(ids, getWeaponName) : "";
  }
</script>

<CastPlate scene="duel" cams={params.cams} guides={params.guides} {seatedSlots}>
  {#each seated as participant, i (i)}
    {@const slot = i + 1}
    {@const hole = layout.holes.find((h) => h.id === `pov${slot}`)!}
    <CastPov
      rect={hole}
      {participant}
      {slot}
      nameplate={false}
      guides={params.guides}
    />
    {#if participant}
      <CastDuelCard
        {participant}
        rank={ranks.get(participant.id) ?? slot}
        avatarUrl={avatars.get(participant.id) ?? null}
        {zoneNames}
        rect={layout.panels[`duel${slot}`]}
        mirrored={slot === 2}
        leader={ranks.get(participant.id) === 1}
        {raceStatus}
        weapons={weaponsOf(participant.id)}
      />
    {/if}
  {/each}
  <CastDuelVersus
    a={seated[0]}
    b={seated[1]}
    rect={layout.panels.versus}
    {raceStatus}
    {totalLayers}
    {ranks}
    layerEntryIgts={raceStore.layerEntryIgts}
    layerSplits={raceStore.layerSplits}
  />
  <CastDesk
    scene="duel"
    race={data.race}
    cams={params.cams}
    casters={params.casters}
    partnerName={data.partnerName}
  />
</CastPlate>
