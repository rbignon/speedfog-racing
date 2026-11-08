<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import SpeedrunTab from "$lib/components/stats/speedrun/SpeedrunTab.svelte";
  import { parseStartRun } from "$lib/speedrun";

  // `?start=random` opens the Start a run window in Random Seed mode,
  // `?start=set&seed=<n>` in Set Seed mode on that seed. Read once, then
  // dropped from the URL (the board's own keys stay), so a reload or a shared
  // link shows the board alone.
  const startRun = parseStartRun(page.url.searchParams);

  onMount(() => {
    const url = new URL(page.url);
    if (!url.searchParams.has("start") && !url.searchParams.has("seed")) return;
    url.searchParams.delete("start");
    url.searchParams.delete("seed");
    goto(url, { replaceState: true, noScroll: true, keepFocus: true });
  });
</script>

<svelte:head>
  <title>Speedrun - SpeedFog Racing</title>
</svelte:head>

<main class="speedrun-page">
  <div class="page-header">
    <h1>Speedrun <span class="beta-badge">Beta</span></h1>
    <p class="subtitle">
      Every category, on blind seeds and on seeds you can replay.
    </p>
  </div>

  <SpeedrunTab {startRun} />
</main>

<style>
  .speedrun-page {
    width: 100%;
    max-width: 1100px;
    margin: 0 auto;
    padding: 2rem;
    box-sizing: border-box;
  }

  .page-header {
    margin-bottom: 1.5rem;
  }

  .page-header h1 {
    margin: 0 0 0.35rem 0;
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--color-text);
  }

  .beta-badge {
    padding: 0.1em 0.4em;
    background: var(--color-gold);
    border-radius: var(--radius-sm);
    color: var(--color-ink-on-accent);
    font-size: 0.4em;
    font-weight: 600;
    letter-spacing: 0.05em;
    vertical-align: super;
  }

  .subtitle {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-base);
  }

  @media (max-width: 640px) {
    .speedrun-page {
      padding: 1rem;
    }
  }
</style>
