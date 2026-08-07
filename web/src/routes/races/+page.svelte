<script lang="ts">
  import { onMount } from "svelte";
  import { fetchRaces, fetchRacesPaginated, type Race } from "$lib/api";
  import RaceCard from "$lib/components/RaceCard.svelte";
  import SectionTitle from "$lib/components/SectionTitle.svelte";

  const FINISHED_PAGE_SIZE = 10;

  let races: Race[] = $state([]);
  let finishedRaces: Race[] = $state([]);
  let loadingRaces = $state(true);
  let loadingFinished = $state(true);
  let loadingMore = $state(false);
  let hasMoreFinished = $state(false);

  let liveRaces = $derived(races.filter((r) => r.status === "running"));
  let upcomingRaces = $derived(
    races
      .filter((r) => r.status === "setup" && r.scheduled_at)
      .sort(
        (a, b) =>
          new Date(a.scheduled_at!).getTime() -
          new Date(b.scheduled_at!).getTime(),
      ),
  );

  onMount(() => {
    fetchRaces("setup,running")
      .then((r) => (races = r))
      .catch((e) => console.error("Failed to fetch races:", e))
      .finally(() => (loadingRaces = false));

    fetchRacesPaginated("finished", 0, FINISHED_PAGE_SIZE)
      .then((data) => {
        finishedRaces = data.races;
        hasMoreFinished = data.has_more ?? false;
      })
      .catch((e) => console.error("Failed to fetch finished races:", e))
      .finally(() => (loadingFinished = false));
  });

  async function loadMoreFinished() {
    loadingMore = true;
    try {
      const data = await fetchRacesPaginated(
        "finished",
        finishedRaces.length,
        FINISHED_PAGE_SIZE,
      );
      finishedRaces = [...finishedRaces, ...data.races];
      hasMoreFinished = data.has_more ?? false;
    } catch (e) {
      console.error("Failed to load more finished races:", e);
    } finally {
      loadingMore = false;
    }
  }
</script>

<svelte:head>
  <title>Races - SpeedFog Racing</title>
</svelte:head>

<main class="races-page">
  <h1>Races</h1>

  {#if loadingRaces}
    <p class="loading">Loading races...</p>
  {:else}
    {#if liveRaces.length > 0}
      <section class="race-section">
        <SectionTitle>Live Races</SectionTitle>
        <div class="race-grid">
          {#each liveRaces as race}
            <RaceCard {race} />
          {/each}
        </div>
      </section>
    {/if}

    {#if upcomingRaces.length > 0}
      <section class="race-section">
        <SectionTitle>Upcoming Races</SectionTitle>
        <div class="race-grid">
          {#each upcomingRaces as race}
            <RaceCard {race} />
          {/each}
        </div>
      </section>
    {/if}

    {#if liveRaces.length === 0 && upcomingRaces.length === 0}
      <div class="empty-active">
        <p class="empty-text">No active races right now</p>
        <a
          href="https://discord.gg/Qmw67J3mR9"
          class="discord-link"
          target="_blank"
          rel="noopener noreferrer"
        >
          <svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"
            ><path
              d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z"
            /></svg
          >
          Find players on Discord
        </a>
      </div>
    {/if}
  {/if}

  <section class="race-section">
    <SectionTitle>Recent Races</SectionTitle>
    {#if loadingFinished}
      <p class="loading">Loading results...</p>
    {:else if finishedRaces.length === 0}
      <p class="empty-text">No finished races yet.</p>
    {:else}
      <div class="race-grid">
        {#each finishedRaces as race}
          <RaceCard {race} />
        {/each}
      </div>
      {#if hasMoreFinished}
        <div class="load-more">
          <button
            class="btn btn-secondary"
            onclick={loadMoreFinished}
            disabled={loadingMore}
          >
            {loadingMore ? "Loading..." : "Load more"}
          </button>
        </div>
      {/if}
    {/if}
  </section>
</main>

<style>
  .races-page {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
    box-sizing: border-box;
  }

  h1 {
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--color-text);
    margin: 0 0 1.5rem;
  }

  .race-section {
    margin-bottom: 2rem;
  }

  .race-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
  }

  .loading {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .empty-active {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    padding: 1.5rem 0;
    text-align: center;
  }

  .discord-link {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    color: var(--color-text-secondary);
    text-decoration: none;
    font-size: var(--font-size-sm);
    transition: color 0.15s ease;
  }

  .discord-link:hover {
    color: #5865f2;
  }

  .empty-text {
    margin: 0;
    color: var(--color-text-secondary);
  }

  .load-more {
    display: flex;
    justify-content: center;
    margin-top: 1.5rem;
  }

  @media (max-width: 640px) {
    .races-page {
      padding: 1rem;
    }

    .race-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
