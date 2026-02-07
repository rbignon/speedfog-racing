<script lang="ts">
	import { auth } from '$lib/stores/auth.svelte';
	import { raceStore } from '$lib/stores/race.svelte';
	import Leaderboard from '$lib/components/Leaderboard.svelte';
	import RaceStatus from '$lib/components/RaceStatus.svelte';

	import SpectatorCount from '$lib/components/SpectatorCount.svelte';
	import ParticipantCard from '$lib/components/ParticipantCard.svelte';
	import ParticipantSearch from '$lib/components/ParticipantSearch.svelte';
	import CasterList from '$lib/components/CasterList.svelte';
	import { MetroDag, MetroDagBlurred, MetroDagLive } from '$lib/dag';
	import { downloadMySeedPack, fetchRace, type RaceDetail } from '$lib/api';

	let downloading = $state(false);
	let downloadError = $state<string | null>(null);
	let showInviteSearch = $state(false);
	let elapsedSeconds = $state(0);

	async function handleDownload() {
		downloading = true;
		downloadError = null;
		try {
			await downloadMySeedPack(initialRace.id);
		} catch (e) {
			downloadError = e instanceof Error ? e.message : 'Download failed';
		} finally {
			downloading = false;
		}
	}

	let { data } = $props();

	let initialRace: RaceDetail = $state(data.race);

	// Update initialRace when route data changes (navigation between races)
	$effect(() => {
		initialRace = data.race;
	});

	// Live data from WebSocket
	let liveRace = $derived(raceStore.race);
	let liveSeed = $derived(raceStore.seed);

	let spectatorCount = $derived(raceStore.spectatorCount);

	// Use live data if available, otherwise fall back to initial
	let raceName = $derived(liveRace?.name ?? initialRace.name);
	let raceStatus = $derived(liveRace?.status ?? initialRace.status);
	let totalLayers = $derived(liveSeed?.total_layers ?? initialRace.seed_total_layers);

	// Merge REST participants with WS live status
	let mergedParticipants = $derived.by(() => {
		const wsStatusMap = new Map(
			raceStore.participants.map((wp) => [wp.twitch_username, wp.status])
		);
		return initialRace.participants.map((p) => ({
			...p,
			liveStatus: wsStatusMap.get(p.user.twitch_username)
		}));
	});

	$effect(() => {
		raceStore.connect(initialRace.id);

		return () => {
			raceStore.disconnect();
		};
	});

	// Cosmetic elapsed clock: starts from 0 on page load, not synced to server.
	// The authoritative time source is IGT from each player's mod.
	$effect(() => {
		if (raceStatus !== 'running') {
			elapsedSeconds = 0;
			return;
		}

		const interval = setInterval(() => {
			elapsedSeconds += 1;
		}, 1000);

		return () => clearInterval(interval);
	});

	function formatElapsed(totalSeconds: number): string {
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		const s = totalSeconds % 60;
		return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
	}

	let isOrganizer = $derived(auth.user?.id === initialRace.organizer.id);

	let isParticipant = $derived.by(() => {
		if (!auth.user) return false;
		const liveParticipants = raceStore.leaderboard;
		if (liveParticipants.length > 0) {
			return liveParticipants.some((p) => p.twitch_username === auth.user?.twitch_username);
		}
		return initialRace.participants.some((p) => p.user.id === auth.user?.id);
	});

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleString();
	}

	async function handleParticipantAdded() {
		showInviteSearch = false;
		initialRace = await fetchRace(initialRace.id);
	}
</script>

<svelte:head>
	<title>{raceName} - SpeedFog Racing</title>
</svelte:head>

<div class="race-page">
	<aside class="sidebar">
		{#if raceStatus === 'draft' || raceStatus === 'open'}
			<div class="sidebar-section">
				<h2>Participants ({mergedParticipants.length})</h2>
				<div class="participant-list">
					{#each mergedParticipants as mp (mp.id)}
						<ParticipantCard
							participant={mp}
							liveStatus={mp.liveStatus}
							isOrganizer={mp.user.id === initialRace.organizer.id}
						/>
					{/each}
				</div>

				{#if isOrganizer}
					{#if showInviteSearch}
						<div class="invite-search">
							<ParticipantSearch
								mode="participant"
								raceId={initialRace.id}
								onAdded={handleParticipantAdded}
								onCancel={() => (showInviteSearch = false)}
							/>
						</div>
					{:else}
						<button class="invite-btn" onclick={() => (showInviteSearch = true)}> + Invite </button>
					{/if}
				{/if}
			</div>
		{:else}
			<Leaderboard participants={raceStore.leaderboard} {totalLayers} />
		{/if}

		<div class="sidebar-footer">
			<SpectatorCount count={spectatorCount} />
		</div>
	</aside>

	<main class="main-content">
		<header class="race-header">
			<div>
				<h1>{raceName}</h1>
				<p class="organizer">
					Organized by {initialRace.organizer.twitch_display_name ||
						initialRace.organizer.twitch_username}
				</p>
			</div>
			<div class="header-right">
				<RaceStatus status={raceStatus} />
				{#if raceStatus === 'running'}
					<span class="elapsed-clock">{formatElapsed(elapsedSeconds)}</span>
				{/if}
			</div>
		</header>

		{#if liveSeed?.graph_json && raceStatus === 'running'}
			<MetroDagLive graphJson={liveSeed.graph_json} participants={raceStore.participants} />
		{:else if liveSeed?.graph_json}
			<MetroDag graphJson={liveSeed.graph_json} />
		{:else if liveSeed?.total_nodes && liveSeed?.total_paths && totalLayers}
			<MetroDagBlurred
				{totalLayers}
				totalNodes={liveSeed.total_nodes}
				totalPaths={liveSeed.total_paths}
			/>
		{:else if totalLayers}
			<div class="dag-placeholder">
				<p class="dag-note">DAG hidden until race starts</p>
			</div>
		{/if}

		<CasterList casters={initialRace.casters} />

		<div class="race-info">
			<div class="info-grid">
				<div class="info-item">
					<span class="label">Pool</span>
					<span class="value">{initialRace.pool_name || 'standard'}</span>
				</div>
				<div class="info-item">
					<span class="label">Participants</span>
					<span class="value">{mergedParticipants.length}</span>
				</div>
				<div class="info-item">
					<span class="label">Created</span>
					<span class="value">{formatDate(initialRace.created_at)}</span>
				</div>
			</div>

			<div class="actions">
				{#if isOrganizer}
					<a href="/race/{initialRace.id}/manage" class="btn btn-primary">Manage Race</a>
				{/if}
				{#if isParticipant}
					{#if !isOrganizer}
						<span class="participant-note">You are participating in this race</span>
					{/if}
					<button class="btn btn-secondary" onclick={handleDownload} disabled={downloading}>
						{downloading ? 'Downloading...' : 'Download Race Package'}
					</button>
					{#if downloadError}
						<span class="download-error">{downloadError}</span>
					{/if}
				{/if}
			</div>
		</div>
	</main>
</div>

<style>
	.race-page {
		display: flex;
		min-height: calc(100vh - 75px);
	}

	.sidebar {
		width: 280px;
		background: var(--color-surface);
		border-right: 1px solid var(--color-border);
		padding: 1.5rem;
		flex-shrink: 0;
		display: flex;
		flex-direction: column;
	}

	.sidebar-section {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow-y: auto;
	}

	.sidebar-section h2 {
		color: var(--color-gold);
		margin: 0 0 1rem 0;
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	.participant-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		overflow-y: auto;
	}

	.invite-btn {
		margin-top: 0.75rem;
		width: 100%;
		padding: 0.75rem;
		border: 2px dashed var(--color-border);
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-base);
		cursor: pointer;
		transition: all var(--transition);
	}

	.invite-btn:hover {
		border-color: var(--color-purple);
		color: var(--color-purple);
	}

	.invite-search {
		margin-top: 0.75rem;
	}

	.sidebar-footer {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding-top: 1rem;
		margin-top: auto;
		border-top: 1px solid var(--color-border);
	}

	.main-content {
		flex: 1;
		padding: 2rem;
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.race-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.race-header h1 {
		margin: 0;
		color: var(--color-text);
		font-size: var(--font-size-2xl);
		font-weight: 600;
	}

	.header-right {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-shrink: 0;
	}

	.elapsed-clock {
		font-size: var(--font-size-lg);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--color-warning, #f59e0b);
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
	}

	.organizer {
		margin: 0.25rem 0 0 0;
		color: var(--color-text-disabled);
	}

	.dag-placeholder {
		min-height: 200px;
		background: var(--color-surface);
		border: 2px dashed var(--color-border);
		border-radius: var(--radius-lg);
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.dag-note {
		color: var(--color-text-disabled);
		font-size: 0.85rem;
		font-style: italic;
		margin: 0;
	}

	.race-info {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 1.5rem;
	}

	.info-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 1rem;
		margin-bottom: 1.5rem;
	}

	.info-item {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.label {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 500;
	}

	.value {
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}

	.actions {
		display: flex;
		gap: 1rem;
		align-items: center;
	}

	.participant-note {
		color: var(--color-success);
		font-style: italic;
	}

	.download-error {
		color: var(--color-danger);
		font-size: 0.9rem;
	}
</style>
