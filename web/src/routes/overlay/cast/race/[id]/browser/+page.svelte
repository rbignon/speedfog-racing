<script lang="ts">
  import CastPlate from "$lib/components/cast/CastPlate.svelte";
  import CastDesk from "$lib/components/cast/CastDesk.svelte";

  let { data } = $props();
  let params = $derived(data.castParams);
</script>

<!-- The whole main area is one hole the caster's own browser capture fills
     from underneath (see layout.ts's browserScene): the page draws nothing
     there, only the desk beneath it. -->
<CastPlate scene="browser" cams={params.cams} guides={params.guides}>
  <CastDesk
    scene="browser"
    race={data.race}
    cams={params.cams}
    casters={params.casters}
    partnerName={data.partnerName}
  />
</CastPlate>
