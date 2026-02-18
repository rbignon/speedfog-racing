<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchRaces, fetchRacesPaginated, type Race } from '$lib/api';
	import RaceCard from '$lib/components/RaceCard.svelte';
	import LiveIndicator from '$lib/components/LiveIndicator.svelte';

	const FINISHED_PAGE_SIZE = 10;

	let races: Race[] = $state([]);
	let finishedRaces: Race[] = $state([]);
	let loadingRaces = $state(true);
	let loadingFinished = $state(true);
	let loadingMore = $state(false);
	let hasMoreFinished = $state(false);

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
		fetchRaces('setup,running')
			.then((r) => (races = r))
			.catch((e) => console.error('Failed to fetch races:', e))
			.finally(() => (loadingRaces = false));

		fetchRacesPaginated('finished', 0, FINISHED_PAGE_SIZE)
			.then((data) => {
				finishedRaces = data.races;
				hasMoreFinished = data.has_more ?? false;
			})
			.catch((e) => console.error('Failed to fetch finished races:', e))
			.finally(() => (loadingFinished = false));
	});

	async function loadMoreFinished() {
		loadingMore = true;
		try {
			const data = await fetchRacesPaginated(
				'finished',
				finishedRaces.length,
				FINISHED_PAGE_SIZE,
			);
			finishedRaces = [...finishedRaces, ...data.races];
			hasMoreFinished = data.has_more ?? false;
		} catch (e) {
			console.error('Failed to load more finished races:', e);
		} finally {
			loadingMore = false;
		}
	}
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
			<div class="empty-active">
				<p class="empty-text">No active races right now</p>
			</div>
		{/if}
	{/if}

	<section class="race-section">
		<h2>Recent Results</h2>
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
					<button class="btn btn-secondary" onclick={loadMoreFinished} disabled={loadingMore}>
						{loadingMore ? 'Loading...' : 'Load more'}
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

	.empty-active {
		padding: 1.5rem 0;
		text-align: center;
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
