<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { site } from '$lib/stores/site.svelte';
	import { fetchRaces, getTwitchLoginUrl, type Race } from '$lib/api';
	import MetroDagAnimated from '$lib/dag/MetroDagAnimated.svelte';
	import RaceCard from '$lib/components/RaceCard.svelte';
	import LiveIndicator from '$lib/components/LiveIndicator.svelte';
	import heroSeed from '$lib/data/hero-seed.json';

	let races: Race[] = $state([]);
	let loadingRaces = $state(true);
	let errorMessage = $state<string | null>(null);

	let liveRaces = $derived(races.filter((r) => r.status === 'running'));
	let upcomingRaces = $derived(
		races
			.filter((r) => r.status === 'setup')
			.sort((a, b) => {
				if (a.scheduled_at && b.scheduled_at)
					return new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime();
				if (a.scheduled_at) return -1;
				if (b.scheduled_at) return 1;
				return 0;
			}),
	);

	onMount(() => {
		const error = page.url.searchParams.get('error');
		if (error) {
			errorMessage = getErrorMessage(error);
			history.replaceState(null, '', '/');
		}

		fetchRaces('setup,running')
			.then((r) => (races = r))
			.catch((e) => console.error('Failed to fetch races:', e))
			.finally(() => (loadingRaces = false));
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

<div class="hero">
	<div class="hero-dag">
		<MetroDagAnimated graphJson={heroSeed} />
	</div>
	<div class="hero-cta">
		<h1>SpeedFog Racing<span class="beta-badge">Beta</span></h1>
		<p class="hero-tagline">Competitive Elden Ring racing through randomized fog gates</p>
		<div class="hero-buttons">
			{#if !site.initialized}
				<!-- Wait for site config before showing CTA -->
			{:else if site.comingSoon}
				<span class="btn btn-primary btn-lg btn-disabled">Coming soon</span>
			{:else if auth.isLoggedIn}
				<a href="/training" class="btn btn-primary btn-lg">Start Training</a>
			{:else}
				<a href={getTwitchLoginUrl()} class="btn btn-primary btn-lg" data-sveltekit-reload
					>Try a seed</a
				>
			{/if}
			<a href="/about" class="btn btn-secondary btn-lg">Learn more</a>
		</div>
		<a
			href="https://discord.gg/Qmw67J3mR9"
			class="discord-link"
			target="_blank"
			rel="noopener noreferrer"
		>
			<svg
				class="discord-icon"
				viewBox="0 0 24 24"
				fill="currentColor"
				width="16"
				height="16"
				><path
					d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z"
				/></svg
			>
			Join our Discord
		</a>
	</div>
</div>

{#if site.initialized && !site.comingSoon}
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
		font-size: clamp(1.5rem, 4vw, 2.5rem);
		font-weight: 700;
		color: var(--color-gold);
		margin: 0 0 0.5rem;
	}

	.beta-badge {
		font-size: 0.3em;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background: var(--color-gold);
		color: var(--color-bg);
		padding: 0.1em 0.4em;
		border-radius: 4px;
		margin-left: 0.4em;
		vertical-align: super;
	}

	.hero-tagline {
		color: var(--color-text-secondary);
		font-size: clamp(0.85rem, 2vw, 1.1rem);
		margin: 0 0 1.5rem;
	}

	.hero-buttons {
		display: flex;
		gap: 1rem;
		align-items: center;
		flex-wrap: wrap;
		justify-content: center;
	}

	.discord-link {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		margin-top: 1rem;
		color: var(--color-text-disabled);
		text-decoration: none;
		font-size: var(--font-size-sm);
		transition: color 0.15s ease;
	}

	.discord-link:hover {
		color: #5865f2;
	}

	.discord-icon {
		width: 1em;
		height: 1em;
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

	.race-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 1rem;
	}

	/* States */
	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
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

	@media (max-width: 640px) {
		.public-section {
			padding: 1rem;
		}

		.race-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
