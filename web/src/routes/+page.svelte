<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { fetchRaces, fetchMyRaces, getTwitchLoginUrl, type Race } from '$lib/api';
	import MetroDagAnimated from '$lib/dag/MetroDagAnimated.svelte';
	import RaceCard from '$lib/components/RaceCard.svelte';
	import LiveIndicator from '$lib/components/LiveIndicator.svelte';
	import heroSeed from '$lib/data/hero-seed.json';

	let races: Race[] = $state([]);
	let myRaces: Race[] = $state([]);
	let loadingRaces = $state(true);
	let loadingMyRaces = $state(false);
	let errorMessage = $state<string | null>(null);
	let myRacesFetched = $state(false);

	// IDs of the user's races, for filtering duplicates from public lists
	let myRaceIds = $derived(new Set(myRaces.map((r) => r.id)));

	// Public race splits
	let liveRaces = $derived(
		races.filter((r) => r.status === 'running' && !myRaceIds.has(r.id)),
	);
	let upcomingRaces = $derived(
		races.filter((r) => r.status === 'open' && !myRaceIds.has(r.id)),
	);

	// User's active race spotlight
	let activeRace = $derived(myRaces.find((r) => r.status === 'running'));

	onMount(() => {
		const error = page.url.searchParams.get('error');
		if (error) {
			errorMessage = getErrorMessage(error);
			history.replaceState(null, '', '/');
		}

		fetchRaces('open,running')
			.then((r) => (races = r))
			.catch((e) => console.error('Failed to fetch races:', e))
			.finally(() => (loadingRaces = false));
	});

	// Fetch my races once auth is initialized
	$effect(() => {
		if (auth.initialized && !myRacesFetched) {
			myRacesFetched = true;
			if (auth.isLoggedIn) {
				loadingMyRaces = true;
				fetchMyRaces()
					.then((r) => (myRaces = r))
					.catch((e) => console.error('Failed to fetch my races:', e))
					.finally(() => (loadingMyRaces = false));
			}
		}
	});

	function getErrorMessage(error: string): string {
		switch (error) {
			case 'auth_failed':
				return 'Authentication failed. Please try again.';
			case 'no_token':
				return 'No authentication token received.';
			case 'invalid_token':
				return 'Invalid authentication token.';
			default:
				return 'An error occurred.';
		}
	}

	// TODO: detect "Casting" role once API exposes caster info in list responses
	function isOrganizer(race: Race): boolean {
		return auth.user?.id === race.organizer.id;
	}
</script>

<svelte:head>
	<title>SpeedFog Racing</title>
</svelte:head>

{#if errorMessage}
	<div class="error-banner">
		{errorMessage}
		<button onclick={() => (errorMessage = null)}>&times;</button>
	</div>
{/if}

{#if auth.isLoggedIn}
	<!-- Connected: Dashboard layout -->
	<main class="dashboard">
		{#if activeRace}
			<section class="spotlight">
				<a href="/race/{activeRace.id}" class="spotlight-card">
					<div class="spotlight-header">
						<LiveIndicator />
						<span class="spotlight-name">{activeRace.name}</span>
					</div>
					<p class="spotlight-meta">
						{activeRace.participant_count} player{activeRace.participant_count !== 1
							? 's'
							: ''} racing
					</p>
				</a>
			</section>
		{/if}

		<section class="my-races">
			<h2>My Races</h2>
			{#if loadingMyRaces}
				<p class="loading">Loading your races...</p>
			{:else if myRaces.length === 0}
				<div class="empty-state">
					<p>You're not in any races yet.</p>
					<a href="/race/new" class="btn btn-primary">Create Race</a>
				</div>
			{:else}
				<div class="race-grid">
					{#each myRaces as race}
						<RaceCard
							{race}
							role={isOrganizer(race) ? 'Organizing' : 'Participating'}
							variant="compact"
						/>
					{/each}
				</div>
			{/if}
		</section>

		{#if liveRaces.length > 0}
			<section class="public-races">
				<h2><LiveIndicator dotOnly /> Live Races</h2>
				<div class="race-grid">
					{#each liveRaces as race}
						<RaceCard {race} />
					{/each}
				</div>
			</section>
		{/if}

		{#if upcomingRaces.length > 0}
			<section class="public-races">
				<h2>Upcoming Races</h2>
				<div class="race-grid">
					{#each upcomingRaces as race}
						<RaceCard {race} />
					{/each}
				</div>
			</section>
		{/if}

		{#if !loadingRaces && liveRaces.length === 0 && upcomingRaces.length === 0}
			<section class="public-races">
				<p class="empty-muted">No public races at the moment.</p>
			</section>
		{/if}
	</main>
{:else}
	<!-- Anonymous: Hero + public races -->
	<div class="hero">
		<div class="hero-dag">
			<MetroDagAnimated graphJson={heroSeed} />
		</div>
		<div class="hero-overlay">
			<h1>SpeedFog Racing</h1>
			<p class="hero-tagline">Competitive Elden Ring racing through randomized fog gates</p>
			<a href={getTwitchLoginUrl()} class="btn btn-twitch btn-lg">Login with Twitch</a>
		</div>
	</div>

	<main class="public-section">
		{#if loadingRaces}
			<p class="loading">Loading races...</p>
		{:else}
			{#if liveRaces.length > 0}
				<section class="public-races">
					<h2><LiveIndicator dotOnly /> Live Races</h2>
					<div class="race-grid">
						{#each liveRaces as race}
							<RaceCard {race} />
						{/each}
					</div>
				</section>
			{/if}

			{#if upcomingRaces.length > 0}
				<section class="public-races">
					<h2>Upcoming Races</h2>
					<div class="race-grid">
						{#each upcomingRaces as race}
							<RaceCard {race} />
						{/each}
					</div>
				</section>
			{/if}

			{#if liveRaces.length === 0 && upcomingRaces.length === 0}
				<p class="empty-muted">No active races at the moment.</p>
			{/if}
		{/if}
	</main>
{/if}

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

	/* Hero section (anonymous) */
	.hero {
		position: relative;
		width: 100%;
		max-height: 40vh;
		overflow: hidden;
		background: var(--color-surface);
	}

	.hero-dag {
		opacity: 0.45;
	}

	.hero-overlay {
		position: absolute;
		inset: 0;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		text-align: center;
		padding: 2rem;
	}

	.hero-overlay h1 {
		font-size: clamp(1.5rem, 4vw, 2.5rem);
		font-weight: 700;
		color: var(--color-gold);
		margin: 0 0 0.5rem;
	}

	.hero-tagline {
		color: var(--color-text-secondary);
		font-size: clamp(0.85rem, 2vw, 1.1rem);
		margin: 0 0 1.5rem;
		max-width: 500px;
	}

	.btn-lg {
		padding: 0.75rem 2rem;
		font-size: 1rem;
	}

	/* Dashboard (connected) */
	.dashboard {
		max-width: 1200px;
		margin: 0 auto;
		padding: 2rem;
	}

	/* Spotlight for active race */
	.spotlight {
		margin-bottom: 2rem;
	}

	.spotlight-card {
		display: block;
		background: var(--color-surface);
		border: 2px solid var(--color-gold);
		border-radius: var(--radius-lg);
		padding: 1.25rem 1.5rem;
		text-decoration: none;
		color: inherit;
		transition:
			box-shadow var(--transition),
			border-color var(--transition);
	}

	.spotlight-card:hover {
		box-shadow: var(--glow-gold);
	}

	.spotlight-header {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-bottom: 0.25rem;
	}

	.spotlight-name {
		font-size: var(--font-size-lg);
		font-weight: 600;
		color: var(--color-text);
	}

	.spotlight-meta {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	/* Sections */
	.public-section {
		max-width: 1200px;
		margin: 0 auto;
		padding: 2rem;
	}

	.my-races,
	.public-races {
		margin-bottom: 2rem;
	}

	h2 {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin: 0 0 1rem;
		color: var(--color-gold);
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	/* Race card grid */
	.race-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
		gap: 1rem;
	}

	/* States */
	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		padding: 2rem;
		color: var(--color-text-secondary);
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		text-align: center;
	}

	.empty-state p {
		margin: 0;
	}

	.empty-muted {
		color: var(--color-text-disabled);
		font-style: italic;
	}
</style>
