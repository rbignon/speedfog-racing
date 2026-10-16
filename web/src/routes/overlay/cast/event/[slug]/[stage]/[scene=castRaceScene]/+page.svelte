<script lang="ts">
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { fetchStageCurrentRace, type StageCurrentRace } from "$lib/api";
  import { FOLLOW_POLL_MS, followStep, followTarget } from "$lib/cast/follow";
  import CastPlate from "$lib/components/cast/CastPlate.svelte";

  let { data } = $props();
  let params = $derived(data.castParams);

  // The load found no race to hand over to (none yet, or no answer): ask
  // again until one exists, one request at a time, then move to it. A
  // navigation that did not take the page away (aborted) resumes polling.
  $effect(() => {
    const { slug, stage, scene } = data;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let stopped = false;
    const ask = async () => {
      let answer: StageCurrentRace | null;
      try {
        answer = await fetchStageCurrentRace(slug, stage);
      } catch {
        answer = null;
      }
      if (stopped) return;
      const { navigateTo } = followStep(null, null, answer);
      if (navigateTo) {
        const target = followTarget(navigateTo, scene, page.url.searchParams, {
          slug,
          stage,
        });
        await goto(target, { replaceState: true }).catch(() => {});
        if (stopped) return;
      }
      timer = setTimeout(ask, FOLLOW_POLL_MS);
    };
    timer = setTimeout(ask, FOLLOW_POLL_MS);
    return () => {
      stopped = true;
      clearTimeout(timer);
    };
  });
</script>

<!-- The scene's opaque plate and nothing on it: no runner is seated, so no
     POV hole is pierced over the caster's sources. -->
<CastPlate
  scene={data.scene}
  cams={params.cams}
  guides={params.guides}
  seatedSlots={[]}
/>
