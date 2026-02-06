<script lang="ts">
	import { onMount } from 'svelte';
	import { page } from '$app/state';
	import { fetchRaces, type Race } from '$lib/api';

	let races: Race[] = $state([]);
	let loadingRaces = $state(true);
	let errorMessage = $state<string | null>(null);

	onMount(async () => {
		// Check for error in URL
		const error = page.url.searchParams.get('error');
		if (error) {
			errorMessage = getErrorMessage(error);
			// Clear error from URL
			history.replaceState(null, '', '/');
		}

		// Fetch races
		try {
			races = await fetchRaces('open,countdown,running');
		} catch (e) {
			console.error('Failed to fetch races:', e);
		} finally {
			loadingRaces = false;
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
</script>

<svelte:head>
	<title>SpeedFog Racing</title>
</svelte:head>

<main>
	{#if errorMessage}
		<div class="error-banner">
			{errorMessage}
			<button onclick={() => (errorMessage = null)}>×</button>
		</div>
	{/if}

	<section class="races">
		<h2>Active Races</h2>

		{#if loadingRaces}
			<p class="loading">Loading races...</p>
		{:else if races.length === 0}
			<p class="empty">No active races at the moment.</p>
		{:else}
			<div class="race-list">
				{#each races as race}
					<a href="/race/{race.id}" class="race-card">
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
		background: #c0392b;
		color: white;
		padding: 1rem;
		border-radius: 4px;
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
		color: #9b59b6;
	}

	.loading,
	.empty {
		color: #7f8c8d;
		font-style: italic;
	}

	.race-list {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.race-card {
		background: #16213e;
		border: 1px solid #0f3460;
		border-radius: 8px;
		padding: 1rem;
		text-decoration: none;
		color: inherit;
		transition: border-color 0.2s;
	}

	.race-card:hover {
		border-color: #9b59b6;
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

	.race-info {
		display: flex;
		gap: 1rem;
		font-size: 0.9rem;
		color: #95a5a6;
		margin-bottom: 0.25rem;
	}

	.race-date {
		font-size: 0.8rem;
		color: #7f8c8d;
	}
</style>
