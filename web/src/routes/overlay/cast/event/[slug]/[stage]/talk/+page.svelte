<script lang="ts">
  import CastPlate from "$lib/components/cast/CastPlate.svelte";
  import CastDesk from "$lib/components/cast/CastDesk.svelte";
  import CastEvening from "$lib/components/cast/CastEvening.svelte";

  let { data } = $props();
  let params = $derived(data.castParams);
</script>

<CastPlate scene="talk" cams={params.cams} guides={params.guides}>
  <CastEvening scene="talk" event={data.event} stage={data.stage} />

  <CastDesk
    scene="talk"
    cams={params.cams}
    casters={data.casters}
    partnerName={data.event.partner_name}
  />
</CastPlate>
