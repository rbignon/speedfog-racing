<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchRaces, type Race } from '$lib/api';
	import RaceCard from '$lib/components/RaceCard.svelte';
	import LiveIndicator from '$lib/components/LiveIndicator.svelte';

	let races: Race[] = $state([]);
	let loadingRaces = $state(true);

	let liveRaces = $derived(races.filter((r) => r.status === 'running'));
	let upcomingRaces = $derived(
		races
			.filter((r) => r.status === 'open')
			.sort((a, b) => {
				if (a.scheduled_at && b.scheduled_at)
					return new Date(a.scheduled_at).getTime() - new Date(b.scheduled_at).getTime();
				if (a.scheduled_at) return -1;
				if (b.scheduled_at) return 1;
				return 0;
			}),
	);

	onMount(() => {
		fetchRaces('open,running')
			.then((r) => (races = r))
			.catch((e) => console.error('Failed to fetch races:', e))
			.finally(() => (loadingRaces = false));
	});
</script>

<svelte:head>
	<title>Races — SpeedFog Racing</title>
</svelte:head>

<main class="races-page">
	<h1>Races</h1>

	{#if loadingRaces}
		<p class="loading">Loading races...</p>
	{:else}
		{#if liveRaces.length > 0}
			<section class="race-section">
				<h2><LiveIndicator dotOnly /> Live Races</h2>
				<div class="race-grid">
					{#each liveRaces as race}
						<RaceCard {race} />
					{/each}
				</div>
			</section>
		{/if}

		{#if upcomingRaces.length > 0}
			<section class="race-section">
				<h2>Upcoming Races</h2>
				<div class="race-grid">
					{#each upcomingRaces as race}
						<RaceCard {race} />
					{/each}
				</div>
			</section>
		{/if}

		{#if liveRaces.length === 0 && upcomingRaces.length === 0}
			<div class="empty-state">
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
				<p class="empty-hint">Races will appear here when organizers create them.</p>
			</div>
		{/if}
	{/if}
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
		color: var(--color-gold);
		font-size: var(--font-size-xl);
		font-weight: 700;
		margin: 0 0 1.5rem;
	}

	.race-section {
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

	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.empty-state {
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

	.empty-hint {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
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
