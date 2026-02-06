<script lang="ts">
	import { auth } from '$lib/stores/auth.svelte';
	import { raceStore } from '$lib/stores/race.svelte';
	import Leaderboard from '$lib/components/Leaderboard.svelte';
	import RaceStatus from '$lib/components/RaceStatus.svelte';
	import ConnectionStatus from '$lib/components/ConnectionStatus.svelte';
	import { downloadMyZip, type RaceDetail } from '$lib/api';

	let downloading = $state(false);
	let downloadError = $state<string | null>(null);

	async function handleDownload() {
		downloading = true;
		downloadError = null;
		try {
			await downloadMyZip(initialRace.id);
		} catch (e) {
			downloadError = e instanceof Error ? e.message : 'Download failed';
		} finally {
			downloading = false;
		}
	}

	let { data } = $props();

	// Initial data from server-side load
	let initialRace: RaceDetail = $derived(data.race);

	// Live data from WebSocket (falls back to initial data if not connected)
	let liveRace = $derived(raceStore.race);
	let liveSeed = $derived(raceStore.seed);
	let liveParticipants = $derived(raceStore.leaderboard);
	let connected = $derived(raceStore.connected);

	// Use live data if available, otherwise fall back to initial
	let raceName = $derived(liveRace?.name ?? initialRace.name);
	let raceStatus = $derived(liveRace?.status ?? initialRace.status);
	let scheduledStart = $derived(liveRace?.scheduled_start ?? initialRace.scheduled_start);
	let totalLayers = $derived(liveSeed?.total_layers ?? initialRace.seed_total_layers);
	let participantCount = $derived(liveParticipants.length || initialRace.participant_count);

	$effect(() => {
		// Connect to WebSocket for live updates
		raceStore.connect(initialRace.id);

		return () => {
			// Disconnect when leaving the page
			raceStore.disconnect();
		};
	});

	function isOrganizer(): boolean {
		return auth.user?.id === initialRace.organizer.id;
	}

	function isParticipant(): boolean {
		if (!auth.user) return false;
		// Check in live participants first, then initial
		if (liveParticipants.length > 0) {
			return liveParticipants.some((p) => {
				// Live participants have twitch_username directly
				return p.twitch_username === auth.user?.twitch_username;
			});
		}
		return initialRace.participants.some((p) => p.user.id === auth.user?.id);
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleString();
	}
</script>

<svelte:head>
	<title>{raceName} - SpeedFog Racing</title>
</svelte:head>

<div class="race-page">
	<aside class="sidebar">
		<Leaderboard participants={liveParticipants} {totalLayers} />
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
				<ConnectionStatus {connected} />
				<RaceStatus status={raceStatus} {scheduledStart} />
			</div>
		</header>

		<div class="dag-placeholder">
			<div class="dag-content">
				<span class="dag-icon">🗺️</span>
				<p>DAG Visualization</p>
				<p class="dag-note">Coming in Phase 2</p>
			</div>
		</div>

		<div class="race-info">
			<div class="info-grid">
				<div class="info-item">
					<span class="label">Seed</span>
					<span class="value">{totalLayers || '?'} layers</span>
				</div>
				<div class="info-item">
					<span class="label">Pool</span>
					<span class="value">{initialRace.pool_name || 'standard'}</span>
				</div>
				<div class="info-item">
					<span class="label">Participants</span>
					<span class="value">{participantCount}</span>
				</div>
				<div class="info-item">
					<span class="label">Created</span>
					<span class="value">{formatDate(initialRace.created_at)}</span>
				</div>
				{#if scheduledStart}
					<div class="info-item">
						<span class="label">Scheduled Start</span>
						<span class="value">{formatDate(scheduledStart)}</span>
					</div>
				{/if}
			</div>

			<div class="actions">
				{#if isOrganizer()}
					<a href="/race/{initialRace.id}/manage" class="btn btn-primary">Manage Race</a>
				{/if}
				{#if isParticipant()}
					{#if !isOrganizer()}
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
		min-height: calc(100vh - 60px);
	}

	.sidebar {
		width: 280px;
		background: #16213e;
		border-right: 1px solid #0f3460;
		padding: 1.5rem;
		flex-shrink: 0;
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
		color: #eee;
	}

	.organizer {
		margin: 0.25rem 0 0 0;
		color: #7f8c8d;
	}

	.header-right {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 0.5rem;
	}

	.dag-placeholder {
		flex: 1;
		min-height: 300px;
		background: #16213e;
		border: 2px dashed #0f3460;
		border-radius: 8px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.dag-content {
		text-align: center;
		color: #7f8c8d;
	}

	.dag-icon {
		font-size: 3rem;
		display: block;
		margin-bottom: 0.5rem;
	}

	.dag-content p {
		margin: 0.25rem 0;
	}

	.dag-note {
		font-size: 0.85rem;
		font-style: italic;
	}

	.race-info {
		background: #16213e;
		border-radius: 8px;
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
		font-size: 0.8rem;
		color: #7f8c8d;
		text-transform: uppercase;
	}

	.value {
		font-weight: 500;
	}

	.actions {
		display: flex;
		gap: 1rem;
		align-items: center;
	}

	.participant-note {
		color: #27ae60;
		font-style: italic;
	}

	.download-error {
		color: #e74c3c;
		font-size: 0.9rem;
	}
</style>
