<script lang="ts">
  import { untrack } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import {
    fetchStageCurrentRace,
    type RaceStatus,
    type StageCurrentRace,
  } from "$lib/api";
  import { auth } from "$lib/stores/auth.svelte";
  import { raceStore } from "$lib/stores/race.svelte";
  import { getEffectiveLocale } from "$lib/stores/locale.svelte";
  import { FOLLOW_POLL_MS, followStep, followTarget } from "$lib/cast/follow";

  let { data, children } = $props();

  // One connection for every cast scene of this race, delayed to match the
  // caster's video when they asked for it.
  $effect(() => {
    if (!auth.initialized) return;
    const locale = untrack(() => getEffectiveLocale());
    raceStore.connect(data.race.id, locale, data.castParams.delayMs);
    return () => raceStore.disconnect();
  });

  // The shown race's live status: the store's once it holds this race, the
  // loaded one until then (right after a follow navigation the store still
  // holds the previous race until it reconnects).
  let status = $derived(
    (raceStore.race?.id === data.race.id
      ? raceStore.race.status
      : data.race.status) as RaceStatus,
  );

  // `?follow=<slug>:<stage>`: while the shown race is not running, ask which
  // race the stage is on and move this scene to it when it changes. One
  // request at a time; the timer dies with the status turning running, with
  // a new race loaded, and with the stage done on this race.
  $effect(() => {
    const follow = data.castParams.follow;
    const raceId = data.race.id;
    if (!follow || status === "running") return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const ask = async () => {
      let answer: StageCurrentRace | null;
      try {
        answer = await fetchStageCurrentRace(follow.slug, follow.stage);
      } catch {
        answer = null;
      }
      if (stopped) return;
      const step = followStep(raceId, status, answer);
      if (step.navigateTo) {
        const scene = page.url.pathname.split("/").pop() ?? "";
        const target = followTarget(
          step.navigateTo,
          scene,
          page.url.searchParams,
          follow,
        );
        // A navigation that lands reloads this layout and ends this loop; one
        // that did not take the scene away (aborted) polls on.
        await goto(target, { replaceState: true }).catch(() => {});
        if (stopped) return;
      }
      if (step.keepPolling) timer = setTimeout(ask, FOLLOW_POLL_MS);
    };
    timer = setTimeout(ask, FOLLOW_POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  });
</script>

{@render children()}
