<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import {
		fetchTrainingPools,
		fetchTrainingSessions,
		createTrainingSession,
		type PoolStats,
		type PoolInfo,
		type TrainingSession,
	} from '$lib/api';
	import PoolSettingsCard from '$lib/components/PoolSettingsCard.svelte';
	import { timeAgo } from '$lib/utils/time';
	import { displayPoolName, formatIgt } from '$lib/utils/training';

	let pools: PoolStats = $state({});
	let sessions: TrainingSession[] = $state([]);
	let loadingPools = $state(true);
	let loadingSessions = $state(true);
	let startingPool = $state<string | null>(null);
	let error = $state<string | null>(null);
	let authChecked = $state(false);

	const poolOrder = ['training_sprint', 'training_standard', 'training_marathon'];

	let sortedPools = $derived(
		poolOrder
			.filter((p) => p in pools)
			.map((p) => [p, pools[p]] as [string, PoolInfo])
			.concat(
				Object.entries(pools)
					.filter(([p]) => !poolOrder.includes(p))
					.map(([p, info]) => [p, info] as [string, PoolInfo]),
			),
	);

	$effect(() => {
		if (auth.initialized && !authChecked) {
			authChecked = true;

			if (!auth.isLoggedIn) {
				goto('/');
				return;
			}

			loadData();
		}
	});

	async function loadData() {
		try {
			const [poolData, sessionData] = await Promise.all([
				fetchTrainingPools(),
				fetchTrainingSessions(),
			]);
			pools = poolData;
			sessions = sessionData;
		} catch (e) {
			console.error('Failed to load training data:', e);
			error = 'Failed to load training data.';
		} finally {
			loadingPools = false;
			loadingSessions = false;
		}
	}

	async function startTraining(poolName: string) {
		startingPool = poolName;
		error = null;

		try {
			const session = await createTrainingSession(poolName);
			goto(`/training/${session.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to start training session.';
			startingPool = null;
		}
	}

</script>

<svelte:head>
	<title>Training - SpeedFog Racing</title>
</svelte:head>

<main class="training-page">
	<h1>Training</h1>
	<p class="subtitle">Practice solo runs to improve your speed and routing.</p>

	{#if error}
		<div class="error-banner">
			{error}
			<button onclick={() => (error = null)}>&times;</button>
		</div>
	{/if}

	<!-- Pool Selection -->
	<section class="section">
		<h2>Start a Run</h2>
		{#if loadingPools}
			<p class="loading">Loading pools...</p>
		{:else if sortedPools.length === 0}
			<p class="empty">No training pools available.</p>
		{:else}
			<div class="pool-grid">
				{#each sortedPools as [poolName, poolInfo]}
					<div class="pool-card">
						{#if poolInfo.pool_config}
							<PoolSettingsCard poolName={displayPoolName(poolName)} poolConfig={poolInfo.pool_config} compact />
						{:else}
							<div class="pool-name">{displayPoolName(poolName)}</div>
						{/if}
						<div class="pool-footer">
							<span class="seed-count">
								{poolInfo.available} seed{poolInfo.available !== 1 ? 's' : ''} available
							</span>
							<button
								class="btn btn-primary"
								disabled={poolInfo.available === 0 || startingPool !== null}
								onclick={() => startTraining(poolName)}
							>
								{#if startingPool === poolName}
									Starting...
								{:else}
									Start
								{/if}
							</button>
						</div>
					</div>
				{/each}
			</div>
		{/if}
	</section>

	<!-- History -->
	<section class="section">
		<h2>History</h2>
		{#if loadingSessions}
			<p class="loading">Loading sessions...</p>
		{:else if sessions.length === 0}
			<p class="empty">No training sessions yet. Start a run above!</p>
		{:else}
			<div class="history-table-wrapper">
				<table class="history-table">
					<thead>
						<tr>
							<th>Pool</th>
							<th>Status</th>
							<th>IGT</th>
							<th>Deaths</th>
							<th>Date</th>
						</tr>
					</thead>
					<tbody>
						{#each sessions as session}
							<tr>
								<td>
									<a href="/training/{session.id}" class="session-link">
										{displayPoolName(session.pool_name)}
									</a>
								</td>
								<td>
									<span class="badge badge-{session.status}">{session.status}</span>
								</td>
								<td class="mono">{formatIgt(session.igt_ms)}</td>
								<td class="mono">{session.death_count}</td>
								<td class="date">{timeAgo(session.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	</section>
</main>

<style>
	.training-page {
		width: 100%;
		max-width: 1000px;
		margin: 0 auto;
		padding: 2rem;
		box-sizing: border-box;
	}

	h1 {
		color: var(--color-gold);
		font-size: var(--font-size-2xl);
		font-weight: 700;
		margin: 0 0 0.25rem;
	}

	.subtitle {
		color: var(--color-text-secondary);
		margin: 0 0 2rem;
	}

	.error-banner {
		background: var(--color-danger-dark);
		color: white;
		padding: 0.75rem 1rem;
		border-radius: var(--radius-md);
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1.5rem;
	}

	.error-banner button {
		background: none;
		border: none;
		color: white;
		font-size: 1.25rem;
		cursor: pointer;
	}

	.section {
		margin-bottom: 2.5rem;
	}

	h2 {
		color: var(--color-gold);
		font-size: var(--font-size-lg);
		font-weight: 600;
		margin: 0 0 1rem;
	}

	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.empty {
		color: var(--color-text-secondary);
	}

	/* Pool cards */
	.pool-grid {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(280px, 1fr));
		gap: 1rem;
	}

	.pool-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 1.25rem;
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.pool-name {
		color: var(--color-gold);
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	.pool-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: auto;
		padding-top: 0.75rem;
		border-top: 1px solid var(--color-border);
	}

	.seed-count {
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
	}

	/* History table */
	.history-table-wrapper {
		overflow-x: auto;
	}

	.history-table {
		width: 100%;
		border-collapse: collapse;
	}

	.history-table th {
		text-align: left;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 500;
		padding: 0.5rem 0.75rem;
		border-bottom: 1px solid var(--color-border);
	}

	.history-table td {
		padding: 0.65rem 0.75rem;
		border-bottom: 1px solid var(--color-border);
		font-size: var(--font-size-sm);
	}

	.history-table tbody tr:hover {
		background: var(--color-surface);
	}

	.session-link {
		color: var(--color-text);
		text-decoration: none;
		font-weight: 500;
	}

	.session-link:hover {
		color: var(--color-purple);
	}

	.mono {
		font-variant-numeric: tabular-nums;
	}

	.date {
		color: var(--color-text-disabled);
	}

	@media (max-width: 640px) {
		.training-page {
			padding: 1rem;
		}

		.pool-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
