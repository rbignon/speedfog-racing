<script lang="ts">
  import { untrack } from "svelte";
  import { auth } from "$lib/stores/auth.svelte";
  import { raceStore } from "$lib/stores/race.svelte";
  import { getEffectiveLocale } from "$lib/stores/locale.svelte";

  let { data, children } = $props();

  // One connection for every cast scene of this race, delayed to match the
  // caster's video when they asked for it.
  $effect(() => {
    if (!auth.initialized) return;
    const locale = untrack(() => getEffectiveLocale());
    raceStore.connect(data.race.id, locale, data.castParams.delayMs);
    return () => raceStore.disconnect();
  });
</script>

{@render children()}
