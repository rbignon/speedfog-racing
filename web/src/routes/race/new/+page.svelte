<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { createRace, fetchPoolStats, type PoolStats } from '$lib/api';

	let name = $state('');
	let poolName = $state('standard');
	let pools: PoolStats = $state({});
	let loading = $state(true);
	let creating = $state(false);
	let error = $state<string | null>(null);
	let authChecked = $state(false);

	$effect(() => {
		if (auth.initialized && !authChecked) {
			authChecked = true;

			// Redirect if not logged in
			if (!auth.isLoggedIn) {
				goto('/');
				return;
			}

			// Fetch pool stats
			loadPools();
		}
	});

	async function loadPools() {
		try {
			pools = await fetchPoolStats();
		} catch (e) {
			console.error('Failed to fetch pools:', e);
			error = 'Failed to load seed pools.';
		} finally {
			loading = false;
		}
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		if (!name.trim()) {
			error = 'Please enter a race name.';
			return;
		}

		creating = true;
		error = null;

		try {
			const race = await createRace(name.trim(), poolName);
			goto(`/race/${race.id}/manage`);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to create race.';
			creating = false;
		}
	}

	function getPoolOptions(pools: PoolStats): [string, number][] {
		return Object.entries(pools).map(([name, stats]) => [name, stats.available]);
	}
</script>

<svelte:head>
	<title>Create Race - SpeedFog Racing</title>
</svelte:head>

<main>
	<h1>Create Race</h1>

	{#if loading}
		<p class="loading">Loading...</p>
	{:else}
		<form onsubmit={handleSubmit}>
			{#if error}
				<div class="error">{error}</div>
			{/if}

			<div class="form-group">
				<label for="name">Race Name</label>
				<input
					type="text"
					id="name"
					bind:value={name}
					placeholder="Enter race name"
					disabled={creating}
					required
				/>
			</div>

			<div class="form-group">
				<label for="pool">Seed Pool</label>
				<select id="pool" bind:value={poolName} disabled={creating}>
					{#each getPoolOptions(pools) as [pool, available]}
						<option value={pool} disabled={available === 0}>
							{pool} ({available} available)
						</option>
					{:else}
						<option value="standard">standard (unknown)</option>
					{/each}
				</select>
			</div>

			<button type="submit" class="btn btn-primary" disabled={creating}>
				{creating ? 'Creating...' : 'Create Race'}
			</button>
		</form>
	{/if}
</main>

<style>
	main {
		max-width: 500px;
		margin: 0 auto;
		padding: 2rem;
	}

	h1 {
		color: var(--color-text);
		font-size: var(--font-size-2xl);
		font-weight: 600;
		margin-bottom: 2rem;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	label {
		font-weight: 500;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	input,
	select {
		padding: 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: 1rem;
	}

	input:focus,
	select:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	input:disabled,
	select:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.error {
		background: var(--color-danger-dark);
		color: white;
		padding: 0.75rem;
		border-radius: var(--radius-sm);
	}

	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	button {
		align-self: flex-start;
	}
</style>
