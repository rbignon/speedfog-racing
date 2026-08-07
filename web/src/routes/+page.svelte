<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { PUBLIC_BASE_URL } from "$env/static/public";
  import { auth } from "$lib/stores/auth.svelte";
  import {
    fetchRaces,
    fetchRacesPaginated,
    fetchDailyWeek,
    getTwitchLoginUrl,
    type Race,
    type DailyWeekResponse,
  } from "$lib/api";
  import MetroDagAnimated from "$lib/dag/MetroDagAnimated.svelte";
  import RaceCard from "$lib/components/RaceCard.svelte";
  import LiveIndicator from "$lib/components/LiveIndicator.svelte";
  import DailyWeekGrid from "$lib/components/DailyWeekGrid.svelte";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
  import RewardsBanner from "$lib/components/RewardsBanner.svelte";
  import heroSeed from "$lib/data/hero-seed.json";

  let races: Race[] = $state([]);
  let loadingRaces = $state(true);
  let recentRaces: Race[] = $state([]);
  let loadingRecent = $state(true);
  let errorMessage = $state<string | null>(null);
  let dailyWeek: DailyWeekResponse | null = $state(null);

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
    const error = page.url.searchParams.get("error");
    if (error) {
      errorMessage = getErrorMessage(error);
      history.replaceState(null, "", "/");
    }

    fetchRaces("setup,running")
      .then((r) => (races = r))
      .catch((e) => console.error("Failed to fetch races:", e))
      .finally(() => (loadingRaces = false));

    fetchRacesPaginated("finished", 0, 2)
      .then((data) => (recentRaces = data.races))
      .catch((e) => console.error("Failed to fetch recent races:", e))
      .finally(() => (loadingRecent = false));

    fetchDailyWeek()
      .then((week) => (dailyWeek = week))
      .catch(() => (dailyWeek = null));
  });

  // When the active "today" cell's window closes, refetch so the grid
  // advances to the new daily without requiring a page reload.
  $effect(() => {
    if (!dailyWeek) return;
    const todayCell = dailyWeek.days.find((d) => d.state === "today");
    if (!todayCell?.ends_at) return;
    const delay = new Date(todayCell.ends_at).getTime() - Date.now();
    if (delay <= 0) return;
    const timer = setTimeout(() => {
      fetchDailyWeek()
        .then((week) => (dailyWeek = week))
        .catch(() => {});
    }, delay);
    return () => clearTimeout(timer);
  });

  function getErrorMessage(error: string): string {
    switch (error) {
      case "auth_failed":
        return "Authentication failed. Please try again.";
      case "no_token":
        return "No authentication token received.";
      case "invalid_token":
        return "Invalid authentication token.";
      default:
        return "An error occurred.";
    }
  }
</script>

<svelte:head>
  <title>SpeedFog Racing</title>
  <meta
    name="description"
    content="Competitive Elden Ring Fog Randomizer racing platform. Race against other players through randomized fog gates in real time."
  />
  <link rel="canonical" href="{PUBLIC_BASE_URL}/" />
</svelte:head>

{#if errorMessage}
  <div class="error-banner">
    {errorMessage}
    <button onclick={() => (errorMessage = null)}>&times;</button>
  </div>
{/if}

<div class="hero">
  <div class="hero-dag">
    <MetroDagAnimated graphJson={heroSeed} />
  </div>
  <div class="hero-cta">
    <h1>SpeedFog <span class="brass">Racing</span></h1>
    <div class="route-hero" aria-hidden="true">
      <span class="tri"></span><span class="line"></span><span class="ring"
      ></span><span class="term"></span>
    </div>
    <p class="hero-tagline">
      Competitive Elden Ring racing through randomized fog gates
    </p>
    <div class="hero-buttons">
      {#if auth.isLoggedIn}
        {#if auth.canCreateRace}
          <a href="/race/new" class="btn btn-primary btn-lg">Create Race</a>
          <a href="/training" class="btn btn-secondary btn-lg">Play Solo</a>
        {:else}
          <a href="/training" class="btn btn-primary btn-lg">Play Solo</a>
          <a href="/about" class="btn btn-secondary btn-lg">Learn more</a>
        {/if}
      {:else}
        <a
          href={getTwitchLoginUrl()}
          class="btn btn-primary btn-lg"
          data-sveltekit-reload>Try a seed</a
        >
        <a href="/about" class="btn btn-secondary btn-lg">Learn more</a>
      {/if}
    </div>
    <a
      href="https://discord.gg/Qmw67J3mR9"
      class="hero-discord"
      target="_blank"
      rel="noopener noreferrer"
    >
      Join the community on Discord
    </a>
  </div>
</div>

<main class="public-section">
  <RewardsBanner />
  {#if dailyWeek}
    <SectionTitle>Daily Seed</SectionTitle>
    <DailyWeekGrid week={dailyWeek} variant="home" />
  {/if}
  {#if !loadingRaces}
    {#if liveRaces.length > 0}
      <section class="public-races">
        <SectionTitle><LiveIndicator dotOnly /> Live Races</SectionTitle>
        <div class="race-grid">
          {#each liveRaces as race}
            <RaceCard {race} />
          {/each}
        </div>
      </section>
    {/if}

    {#if upcomingRaces.length > 0}
      <section class="public-races">
        <SectionTitle>Upcoming Races</SectionTitle>
        <div class="race-grid">
          {#each upcomingRaces as race}
            <RaceCard {race} />
          {/each}
        </div>
      </section>
    {/if}

    {#if liveRaces.length === 0 && upcomingRaces.length === 0 && !dailyWeek}
      <div class="empty-hero">
        <svg
          class="empty-icon"
          viewBox="0 0 24 24"
          fill="none"
          stroke="currentColor"
          stroke-width="1.5"
          stroke-linecap="round"
          stroke-linejoin="round"
        >
          <circle cx="12" cy="12" r="10" />
          <polyline points="12 6 12 12 16 14" />
        </svg>
        <p class="empty-title">No active races right now</p>
      </div>
    {/if}
  {/if}

  {#if !loadingRecent && recentRaces.length > 0}
    <section class="public-races">
      <SectionTitle>Recent Races</SectionTitle>
      <div class="race-grid">
        {#each recentRaces as race}
          <RaceCard {race} />
        {/each}
      </div>
      <div class="see-all">
        <a href="/races" class="see-all-link">See all results</a>
      </div>
    </section>
  {/if}
</main>

<style>
  /* Error banner */
  .error-banner {
    background: var(--color-danger-dark);
    color: white;
    padding: 1rem 2rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .error-banner button {
    background: none;
    border: none;
    color: white;
    font-size: 1.5rem;
    cursor: pointer;
  }

  /* Hero section */
  .hero {
    width: 100%;
    background: var(--color-surface);
    padding-bottom: 2.5rem;
    overflow: hidden;
  }

  .hero-dag {
    min-width: 600px;
    margin: 0 auto;
  }

  .hero-cta {
    display: flex;
    flex-direction: column;
    align-items: center;
    text-align: center;
    padding: 0 2rem;
  }

  .hero-cta h1 {
    font-family: var(--font-display);
    font-size: clamp(2.2rem, 6vw, 3.6rem);
    font-weight: 700;
    letter-spacing: 0.045em;
    text-transform: uppercase;
    line-height: 1.05;
    color: var(--color-text);
    margin: 0;
  }

  .hero-cta h1 .brass {
    font-weight: 600;
    color: var(--color-gold);
  }

  /* Brass route underline: triangle -> ring -> terminal square */
  .route-hero {
    position: relative;
    width: min(400px, 70vw);
    height: 16px;
    margin: 0.55rem 0 0;
  }

  .route-hero .line {
    position: absolute;
    left: 16px;
    right: 18px;
    top: 7px;
    border-top: 2px solid var(--color-gold);
  }

  .route-hero .tri {
    position: absolute;
    left: 2px;
    top: 2px;
    width: 0;
    height: 0;
    border-left: 10px solid var(--color-gold);
    border-top: 6px solid transparent;
    border-bottom: 6px solid transparent;
  }

  .route-hero .ring {
    position: absolute;
    left: 50%;
    top: 2px;
    width: 12px;
    height: 12px;
    margin-left: -6px;
    border-radius: 50%;
    border: 2px solid var(--color-gold);
    background: var(--color-surface);
  }

  .route-hero .term {
    position: absolute;
    right: 2px;
    top: 3px;
    width: 10px;
    height: 10px;
    background: var(--color-gold);
  }

  .hero-tagline {
    color: var(--color-text-secondary);
    font-size: clamp(0.85rem, 2vw, 1.1rem);
    margin: 1.1rem 0 1.5rem;
  }

  .hero-buttons {
    display: flex;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
    justify-content: center;
  }

  .hero-discord {
    margin-top: 1.5rem;
    color: var(--color-text-secondary);
    text-decoration: none;
    font-size: var(--font-size-sm);
    transition: color 0.15s ease;
  }

  .hero-discord:hover {
    color: var(--color-purple-hover);
  }

  /* Public races */
  .public-section {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
    box-sizing: border-box;
  }

  .public-races {
    margin-bottom: 2rem;
    margin-top: 2rem;
  }

  .race-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 1rem;
  }

  .empty-hero {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.75rem;
    padding: 3rem 2rem;
    margin: 1rem auto;
    max-width: 400px;
    text-align: center;
  }

  .empty-icon {
    width: 3rem;
    height: 3rem;
    color: var(--color-text-disabled);
    opacity: 0.6;
  }

  .empty-title {
    margin: 0;
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--color-text-secondary);
  }

  .see-all {
    display: flex;
    justify-content: center;
    margin-top: 1rem;
  }

  .see-all-link {
    color: var(--color-text-secondary);
    text-decoration: none;
    font-size: var(--font-size-sm);
    transition: color 0.15s ease;
  }

  .see-all-link:hover {
    color: var(--color-purple);
  }

  @media (max-width: 640px) {
    .public-section {
      padding: 1rem;
    }

    .race-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
