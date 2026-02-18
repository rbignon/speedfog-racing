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
	import TrainingSessionCard from '$lib/components/TrainingSessionCard.svelte';
	import { timeAgo } from '$lib/utils/time';
	import { displayPoolName, formatIgt } from '$lib/utils/training';

	let pools: PoolStats = $state({});
	let sessions: TrainingSession[] = $state([]);
	let selectedPool = $state<string | null>(null);
	let loadingPools = $state(true);
	let loadingSessions = $state(true);
	let startingPool = $state<string | null>(null);
	let error = $state<string | null>(null);
	let authChecked = $state(false);

	const poolOrder = ['training_sprint', 'training_standard', 'training_hardcore'];

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

	let selectedConfig = $derived(selectedPool ? pools[selectedPool]?.pool_config ?? null : null);
	let selectedInfo = $derived(selectedPool ? pools[selectedPool] ?? null : null);
	let activeSessions = $derived(sessions.filter((s) => s.status === 'active'));

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
			// Default to first pool with available seeds
			const available = sortedPools.find(([, info]) => info.available > 0);
			if (available) selectedPool = available[0];
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
			// Refresh sessions so UI reflects server state (e.g., 409 = active session exists)
			try {
				sessions = await fetchTrainingSessions();
			} catch {
				// ignore refresh failure
			}
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

	<!-- Active Sessions or Pool Selection -->
	<section class="section">
		{#if loadingPools || loadingSessions}
			<h2>Start a Run</h2>
			<p class="loading">Loading...</p>
		{:else if activeSessions.length > 0}
			<h2>Active Run{activeSessions.length > 1 ? 's' : ''}</h2>
			<div class="active-sessions">
				{#each activeSessions as session (session.id)}
					<TrainingSessionCard {session} />
				{/each}
			</div>
		{:else}
			<h2>Start a Run</h2>
			{#if sortedPools.length === 0}
				<p class="empty">No training pools available.</p>
			{:else}
				<div class="pool-cards">
					{#each sortedPools as [pool, info] (pool)}
						{@const disabled = info.available === 0}
						<button
							type="button"
							class="pool-card"
							class:selected={selectedPool === pool}
							class:disabled
							onclick={() => { if (!disabled && !startingPool) selectedPool = pool; }}
						>
							<span class="pool-name">{displayPoolName(pool)}</span>
							{#if info.pool_config?.estimated_duration}
								<span class="pool-duration">{info.pool_config.estimated_duration}</span>
							{/if}
							{#if info.pool_config?.description}
								<span class="pool-desc">{info.pool_config.description}</span>
							{/if}
							<span class="pool-seeds" class:pool-exhausted={info.played_by_user != null && info.played_by_user >= info.available}>
								{#if info.played_by_user != null && info.played_by_user > 0}
									{info.played_by_user}/{info.available} seed{info.available !== 1 ? 's' : ''} played
									{#if info.played_by_user >= info.available}
										— seeds will repeat
									{/if}
								{:else}
									{info.available} seed{info.available !== 1 ? 's' : ''} available
								{/if}
							</span>
						</button>
					{/each}
				</div>
				{#if selectedPool && selectedConfig}
					<div class="pool-detail">
						<PoolSettingsCard poolName={displayPoolName(selectedPool)} poolConfig={selectedConfig} compact />
						<div class="pool-detail-footer">
							<span class="seed-count" class:pool-exhausted={selectedInfo?.played_by_user != null && selectedInfo.played_by_user >= (selectedInfo?.available ?? 0)}>
								{#if selectedInfo?.played_by_user != null && selectedInfo.played_by_user > 0}
									{selectedInfo.played_by_user}/{selectedInfo.available} seed{selectedInfo.available !== 1 ? 's' : ''} played
									{#if selectedInfo.played_by_user >= selectedInfo.available}
										— seeds will repeat
									{/if}
								{:else}
									{selectedInfo?.available ?? 0} seed{(selectedInfo?.available ?? 0) !== 1 ? 's' : ''} available
								{/if}
							</span>
							<button
								class="btn btn-primary"
								disabled={(selectedInfo?.available ?? 0) === 0 || startingPool !== null}
								onclick={() => startTraining(selectedPool!)}
							>
								{#if startingPool === selectedPool}
									Starting...
								{:else}
									Start
								{/if}
							</button>
						</div>
					</div>
				{/if}
			{/if}
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

	/* Active session cards */
	.active-sessions {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
		max-width: 480px;
	}

	/* Pool selector cards */
	.pool-cards {
		display: flex;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.pool-card {
		flex: 1;
		min-width: 140px;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		padding: 1rem;
		border: 2px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		cursor: pointer;
		text-align: left;
		transition:
			border-color 0.15s,
			background-color 0.15s;
	}

	.pool-card:hover:not(.disabled) {
		border-color: var(--color-text-secondary);
	}

	.pool-card.selected {
		border-color: var(--color-gold);
		background: var(--color-surface-elevated);
	}

	.pool-card.disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.pool-name {
		font-weight: 600;
		font-size: var(--font-size-lg);
	}

	.pool-duration {
		color: var(--color-gold);
		font-size: var(--font-size-sm);
		font-weight: 500;
	}

	.pool-desc {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		line-height: 1.3;
	}

	.pool-seeds {
		margin-top: 0.25rem;
		color: var(--color-text-disabled);
		font-size: var(--font-size-xs);
	}

	.pool-exhausted {
		color: var(--color-gold);
	}

	/* Pool detail panel */
	.pool-detail {
		margin-top: 1rem;
	}

	.pool-detail-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-top: 1rem;
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

		.pool-cards {
			flex-direction: column;
		}
	}
</style>
