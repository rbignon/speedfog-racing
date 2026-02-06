<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { fetchRaces, fetchMyRaces, type Race } from '$lib/api';

	let races: Race[] = $state([]);
	let myRaces: Race[] = $state([]);
	let loadingRaces = $state(true);
	let loadingMyRaces = $state(false);
	let errorMessage = $state<string | null>(null);
	let myRacesFetched = $state(false);

	// IDs of the user's races, for filtering duplicates from active list
	let myRaceIds = $derived(new Set(myRaces.map((r) => r.id)));
	let filteredRaces = $derived(races.filter((r) => !myRaceIds.has(r.id)));

	onMount(() => {
		// Check for error in URL
		const error = page.url.searchParams.get('error');
		if (error) {
			errorMessage = getErrorMessage(error);
			// Clear error from URL
			history.replaceState(null, '', '/');
		}

		// Fetch active races (doesn't depend on auth)
		fetchRaces('open,countdown,running')
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

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString();
	}

	function isOrganizer(race: Race): boolean {
		return auth.user?.id === race.organizer.id;
	}
</script>

<svelte:head>
	<title>SpeedFog Racing</title>
</svelte:head>

<main>
	{#if errorMessage}
		<div class="error-banner">
			{errorMessage}
			<button onclick={() => (errorMessage = null)}>&times;</button>
		</div>
	{/if}

	{#if auth.isLoggedIn}
		<section class="races my-races">
			<h2>My Races</h2>

			{#if loadingMyRaces}
				<p class="loading">Loading your races...</p>
			{:else if myRaces.length === 0}
				<p class="empty">You are not participating in any races yet.</p>
			{:else}
				<div class="race-list">
					{#each myRaces as race}
						<a href="/race/{race.id}" class="race-card" class:running={race.status === 'running'}>
							<div class="race-header">
								<span class="race-name">{race.name}</span>
								<div class="race-badges">
									<span class="badge badge-role"
										>{isOrganizer(race) ? 'Organizing' : 'Participating'}</span
									>
									<span class="badge badge-{race.status}">{race.status}</span>
								</div>
							</div>
							<div class="race-info">
								<span
									>Organizer: {race.organizer.twitch_display_name ||
										race.organizer.twitch_username}</span
								>
								<span
									>{race.participant_count} participant{race.participant_count !== 1
										? 's'
										: ''}</span
								>
							</div>
							<div class="race-date">
								Created {formatDate(race.created_at)}
							</div>
						</a>
					{/each}
				</div>
			{/if}
		</section>
	{/if}

	<section class="races">
		<h2>Active Races</h2>

		{#if loadingRaces}
			<p class="loading">Loading races...</p>
		{:else if filteredRaces.length === 0}
			<p class="empty">No active races at the moment.</p>
		{:else}
			<div class="race-list">
				{#each filteredRaces as race}
					<a href="/race/{race.id}" class="race-card" class:running={race.status === 'running'}>
						<div class="race-header">
							<span class="race-name">{race.name}</span>
							<span class="badge badge-{race.status}">{race.status}</span>
						</div>
						<div class="race-info">
							<span
								>Organizer: {race.organizer.twitch_display_name ||
									race.organizer.twitch_username}</span
							>
							<span
								>{race.participant_count} participant{race.participant_count !== 1 ? 's' : ''}</span
							>
						</div>
						<div class="race-date">
							Created {formatDate(race.created_at)}
						</div>
					</a>
				{/each}
			</div>
		{/if}
	</section>
</main>

<style>
	main {
		max-width: 1200px;
		margin: 0 auto;
		padding: 2rem;
	}

	.error-banner {
		background: var(--color-danger-dark);
		color: white;
		padding: 1rem;
		border-radius: var(--radius-sm);
		margin-bottom: 1rem;
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

	h2 {
		margin-bottom: 1rem;
		color: var(--color-gold);
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	.loading,
	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.my-races {
		margin-bottom: 2rem;
	}

	.race-list {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.race-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 1.25rem;
		text-decoration: none;
		color: inherit;
		transition: border-color var(--transition);
	}

	.race-card:hover {
		border-color: var(--color-purple);
	}

	.race-card.running {
		border-left: 3px solid var(--color-gold);
	}

	.race-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.5rem;
	}

	.race-name {
		font-size: 1.1rem;
		font-weight: 500;
	}

	.race-badges {
		display: flex;
		gap: 0.5rem;
	}

	.badge-role {
		background: rgba(107, 114, 128, 0.2);
		color: var(--color-text-secondary);
	}

	.race-info {
		display: flex;
		gap: 1rem;
		font-size: 0.9rem;
		color: var(--color-text-secondary);
		margin-bottom: 0.25rem;
	}

	.race-date {
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
	}
</style>
