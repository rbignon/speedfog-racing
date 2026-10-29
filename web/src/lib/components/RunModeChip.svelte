<script lang="ts">
  import type { RunMode } from "$lib/api";

  let { mode }: { mode: RunMode } = $props();
</script>

{#if mode === "speedrun" || mode === "set_seed"}
  <span class="chip run-mode-chip" class:speedrun={mode === "speedrun"}
    >{mode === "speedrun" ? "Speedrun" : "Set Seed"}</span
  >
{/if}

<style>
  .run-mode-chip {
    padding: 0.1rem 0.4rem;
    font-size: 0.62rem;
    color: var(--color-purple);
    border-color: color-mix(in srgb, var(--color-purple) 60%, transparent);
  }

  .run-mode-chip.speedrun {
    color: var(--color-success);
    border-color: color-mix(in srgb, var(--color-success) 60%, transparent);
  }
</style>
