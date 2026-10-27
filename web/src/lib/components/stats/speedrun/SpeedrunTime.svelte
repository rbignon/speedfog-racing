<script lang="ts">
  import { speedrunTimeParts } from "$lib/speedrun";
  import { formatIgt } from "$lib/utils/training";

  let { ms }: { ms: number } = $props();

  let parts = $derived(speedrunTimeParts(ms));
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
