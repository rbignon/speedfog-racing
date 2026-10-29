<script lang="ts">
  import SpeedrunTab from "$lib/components/stats/speedrun/SpeedrunTab.svelte";
</script>

<svelte:head>
  <title>Speedrun - SpeedFog Racing</title>
</svelte:head>

<main class="speedrun-page">
  <div class="page-header">
    <h1>Speedrun</h1>
    <p class="subtitle">
      Every category, on blind seeds and on seeds you can replay.
    </p>
  </div>

  <SpeedrunTab />
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
