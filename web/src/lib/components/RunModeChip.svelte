<script lang="ts">
  import type { RunMode } from "$lib/api";

  // Outside the speedrun boards the chip names both the context and the
  // subcategory; `short` keeps a short subcategory alone, for narrow cards
  // inside the speedrun page.
  let { mode, short = false }: { mode: RunMode; short?: boolean } = $props();

  let label = $derived(
    mode === "speedrun"
      ? short
        ? "Random"
        : "Speedrun · Random Seed"
      : short
        ? "Set Seed"
        : "Speedrun · Set Seed",
  );
</script>

{#if mode === "speedrun" || mode === "set_seed"}
  <span class="chip run-mode-chip" class:speedrun={mode === "speedrun"}
    >{label}</span
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
