<script lang="ts">
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { trainingStore } from '$lib/stores/training.svelte';
	import {
		fetchTrainingSession,
		abandonTrainingSession,
		downloadTrainingPack,
		type TrainingSessionDetail
	} from '$lib/api';
	import { MetroDag, MetroDagProgressive, MetroDagResults } from '$lib/dag';
	import ShareButtons from '$lib/components/ShareButtons.svelte';
	import { displayPoolName, formatIgt } from '$lib/utils/training';

	let sessionId = $derived(page.params.id!);
	let session = $state<TrainingSessionDetail | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let showFullDag = $state(false);
	let abandoning = $state(false);
	let downloading = $state(false);
	let confirmAbandon = $state(false);

	// Live data from WS
	let liveParticipant = $derived(trainingStore.participant);
	let liveRace = $derived(trainingStore.race);

	let status = $derived(
		liveRace?.status === 'finished' ? 'finished' : (session?.status ?? 'active')
	);
	let igtMs = $derived(liveParticipant?.igt_ms ?? session?.igt_ms ?? 0);
	let deathCount = $derived(liveParticipant?.death_count ?? session?.death_count ?? 0);
	let currentLayer = $derived(liveParticipant?.current_layer ?? 0);
	let totalLayers = $derived(session?.seed_total_layers ?? 0);

	let isOwner = $derived(auth.isLoggedIn && session?.user?.id === auth.user?.id);

	let graphJson = $derived(trainingStore.seed?.graph_json ?? session?.graph_json ?? null);

	// Build a WsParticipant-compatible object for DAG components
	let dagParticipants = $derived.by(() => {
		if (!liveParticipant) return [];
		return [liveParticipant];
	});

	$effect(() => {
		if (!auth.initialized) return;

		loadSession();
		trainingStore.connect(sessionId);

		return () => {
			trainingStore.disconnect();
		};
	});

	async function loadSession() {
		try {
			session = await fetchTrainingSession(sessionId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load session.';
		} finally {
			loading = false;
		}
	}

	async function handleAbandon() {
		if (!confirmAbandon) {
			confirmAbandon = true;
			return;
		}
		abandoning = true;
		error = null;
		try {
			session = await abandonTrainingSession(sessionId);
			confirmAbandon = false;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to abandon session.';
		} finally {
			abandoning = false;
		}
	}

	async function handleDownload() {
		downloading = true;
		error = null;
		try {
			await downloadTrainingPack(sessionId);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Download failed.';
		} finally {
			downloading = false;
		}
	}
</script>

<svelte:head>
	<title>
		{session ? `Training — ${displayPoolName(session.pool_name)}` : 'Training'} - SpeedFog Racing
	</title>
</svelte:head>

<main class="training-detail">
	{#if loading}
		<p class="loading">Loading session...</p>
	{:else if error && !session}
		<div class="error-state">
			<p>{error}</p>
			<a href="/training" class="btn btn-secondary">Back to Training</a>
		</div>
	{:else if session}
		<!-- Header -->
		<div class="header">
			<div class="header-left">
				<a href="/training" class="back-link">&larr; Training</a>
				<h1>{displayPoolName(session.pool_name)}</h1>
				{#if session.user}
					<span class="player-name">
						by
						<a href="/user/{session.user.twitch_username}" class="player-link">
							{#if session.user.twitch_avatar_url}
								<img src={session.user.twitch_avatar_url} alt="" class="player-avatar" />
							{/if}
							{session.user.twitch_display_name || session.user.twitch_username}
						</a>
					</span>
				{/if}
			</div>
			<div class="header-right">
				<ShareButtons />
				{#if session.seed_number}
					<span class="seed-badge">Seed {session.seed_number}</span>
				{/if}
				<span class="badge badge-{status}">{status}</span>
			</div>
		</div>

		{#if error}
			<div class="error-banner">
				{error}
				<button onclick={() => (error = null)}>&times;</button>
			</div>
		{/if}

		<!-- Stats bar -->
		<div class="stats-bar">
			<div class="stat">
				<span class="stat-label">IGT</span>
				<span class="stat-value mono">{formatIgt(igtMs)}</span>
			</div>
			<div class="stat">
				<span class="stat-label">Deaths</span>
				<span class="stat-value mono">{deathCount}</span>
			</div>
			<div class="stat">
				<span class="stat-label">Progress</span>
				<span class="stat-value mono">{Math.min(currentLayer + 1, totalLayers || Infinity)}/{totalLayers}</span>
			</div>
			{#if liveParticipant?.mod_connected}
				<div class="stat">
					<span class="stat-label">Live</span>
					<span class="stat-value connected-dot">&#x25CF;</span>
				</div>
			{/if}
		</div>

		<!-- DAG section -->
		{#if graphJson}
			<section class="dag-section">
				{#if status === 'finished' && dagParticipants.length > 0}
					<MetroDagResults {graphJson} participants={dagParticipants} />
				{:else if status === 'active' && dagParticipants.length > 0}
					<button class="btn btn-secondary btn-sm" onclick={() => (showFullDag = !showFullDag)}>
						{showFullDag ? 'Hide Spoiler' : 'Show Spoiler'}
					</button>
					<div class="dag-wrapper">
						{#if showFullDag}
							<MetroDagResults {graphJson} participants={dagParticipants} />
						{:else}
							<MetroDagProgressive
								{graphJson}
								participants={dagParticipants}
								myParticipantId={liveParticipant?.id ?? ''}
							/>
						{/if}
					</div>
				{:else}
					<MetroDag {graphJson} />
				{/if}
			</section>
		{/if}

		<!-- Actions (owner only) -->
		{#if isOwner}
			<div class="actions">
				{#if status === 'active'}
					<button class="btn btn-secondary" disabled={downloading} onclick={handleDownload}>
						{downloading ? 'Downloading...' : 'Download Pack'}
					</button>
				{/if}

				{#if status === 'active'}
					{#if confirmAbandon}
						<div class="confirm-group">
							<span class="confirm-text">Abandon this run?</span>
							<button class="btn btn-danger" disabled={abandoning} onclick={handleAbandon}>
								{abandoning ? 'Abandoning...' : 'Confirm'}
							</button>
							<button class="btn btn-secondary" onclick={() => (confirmAbandon = false)}>
								Cancel
							</button>
						</div>
					{:else}
						<button class="btn btn-danger-outline" onclick={handleAbandon}> Abandon </button>
					{/if}
				{/if}
			</div>
		{/if}
	{/if}
</main>

<style>
	.training-detail {
		width: 100%;
		max-width: 1000px;
		margin: 0 auto;
		padding: 2rem;
		box-sizing: border-box;
	}

	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.error-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		padding: 3rem;
		color: var(--color-text-secondary);
	}

	/* Header */
	.header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 1.5rem;
	}

	.header-left {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.back-link {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-decoration: none;
	}

	.back-link:hover {
		color: var(--color-purple);
	}

	h1 {
		color: var(--color-gold);
		font-size: var(--font-size-2xl);
		font-weight: 700;
		margin: 0;
	}

	.player-name {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}

	.player-link {
		color: inherit;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		gap: 0.25rem;
	}

	.player-link:hover {
		color: var(--color-purple);
		text-decoration: underline;
	}

	.player-avatar {
		width: 18px;
		height: 18px;
		border-radius: 50%;
		object-fit: cover;
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

	/* Stats bar */
	.stats-bar {
		display: flex;
		gap: 2rem;
		padding: 1rem 1.5rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		margin-bottom: 1.5rem;
	}

	.stat {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.stat-label {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 500;
	}

	.stat-value {
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	.mono {
		font-variant-numeric: tabular-nums;
	}

	.seed-badge {
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: var(--font-size-xs);
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: 0.2rem 0.5rem;
		color: var(--color-text-secondary);
	}

	.connected-dot {
		color: var(--color-success);
	}

	/* DAG section */
	.dag-section {
		margin-bottom: 1.5rem;
	}

	.dag-wrapper {
		margin-top: 0.75rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		overflow: hidden;
	}

	:global(.training-detail .dag-section svg) {
		min-height: 500px;
	}

	/* Actions */
	.actions {
		display: flex;
		gap: 1rem;
		align-items: center;
		flex-wrap: wrap;
	}

	.confirm-group {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.confirm-text {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	/* Danger outline button */
	:global(.btn-danger-outline) {
		background: transparent;
		color: var(--color-danger);
		border: 1px solid var(--color-danger);
	}

	:global(.btn-danger-outline:hover) {
		background: rgba(220, 38, 38, 0.1);
	}

	:global(.btn-danger) {
		background: var(--color-danger);
		color: white;
	}

	:global(.btn-sm) {
		font-size: var(--font-size-sm);
		padding: 0.35rem 0.75rem;
	}

	@media (max-width: 640px) {
		.training-detail {
			padding: 1rem;
		}

		.stats-bar {
			gap: 1rem;
			flex-wrap: wrap;
		}
	}
</style>
