<script lang="ts">
  import { speedrunGainParts, speedrunTimeParts } from "$lib/speedrun";
  import { formatIgt } from "$lib/utils/training";

  /** `gain`: a record gain, which can be under a second. */
  let { ms, gain = false }: { ms: number; gain?: boolean } = $props();

  let parts = $derived(gain ? speedrunGainParts(ms) : speedrunTimeParts(ms));
  let full = $derived(`${formatIgt(ms)}.${String(ms % 1000).padStart(3, "0")}`);
</script>

<span class="sr-time" title={full}
  >{#each parts as part, i (part.unit)}{i > 0 ? " " : ""}{part.value}<small
      >{part.unit}</small
    >{/each}</span
>

<style>
  .sr-time {
    font-family: var(--font-mono);
    font-weight: 500;
    white-space: nowrap;
  }

  small {
    font-size: 0.68em;
    color: var(--color-text-secondary);
    margin-left: 0.05em;
  }
</style>
