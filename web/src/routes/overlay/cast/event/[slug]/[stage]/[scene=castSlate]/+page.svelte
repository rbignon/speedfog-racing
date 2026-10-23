<script lang="ts">
  import { sceneLayout } from "$lib/cast/layout";
  import CastPlate from "$lib/components/cast/CastPlate.svelte";
  import CastEvening from "$lib/components/cast/CastEvening.svelte";
  import CastSlateHero from "$lib/components/cast/CastSlateHero.svelte";

  let { data } = $props();
  let hero = $derived(sceneLayout(data.scene).panels.hero);
</script>

<CastPlate scene={data.scene}>
  <CastEvening scene={data.scene} event={data.event} stage={data.stage}>
    {#snippet children(stage, nextLabels)}
      <CastSlateHero
        scene={data.scene}
        rect={hero}
        eventName={data.event.name}
        partnerName={data.event.partner_name}
        {stage}
        {nextLabels}
      />
    {/snippet}
  </CastEvening>
</CastPlate>
