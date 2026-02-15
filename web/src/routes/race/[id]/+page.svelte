<script lang="ts">
	import { auth } from '$lib/stores/auth.svelte';
	import { raceStore } from '$lib/stores/race.svelte';
	import Leaderboard from '$lib/components/Leaderboard.svelte';
	import RaceStatus from '$lib/components/RaceStatus.svelte';

	import SpectatorCount from '$lib/components/SpectatorCount.svelte';
	import ParticipantCard from '$lib/components/ParticipantCard.svelte';
	import InviteCard from '$lib/components/InviteCard.svelte';
	import ParticipantSearch from '$lib/components/ParticipantSearch.svelte';
	import CasterList from '$lib/components/CasterList.svelte';
	import RaceControls from '$lib/components/RaceControls.svelte';
	import Podium from '$lib/components/Podium.svelte';
	import PoolSettingsCard from '$lib/components/PoolSettingsCard.svelte';
	import RaceStats from '$lib/components/RaceStats.svelte';
	import ShareButtons from '$lib/components/ShareButtons.svelte';
	import { MetroDag, MetroDagBlurred, MetroDagLive, MetroDagProgressive, MetroDagResults } from '$lib/dag';
	import { parseDagGraph } from '$lib/dag/types';
	import {
		downloadMySeedPack,
		removeParticipant,
		deleteInvite,
		fetchRace,
		type RaceDetail
	} from '$lib/api';

	let downloading = $state(false);
	let downloadError = $state<string | null>(null);
	let showInviteSearch = $state(false);
	let now = $state(Date.now());

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
	let totalNodes = $derived(liveSeed?.total_nodes ?? initialRace.seed_total_nodes);
	let totalPaths = $derived(liveSeed?.total_paths ?? initialRace.seed_total_paths);

	// Build node ID → display name map for leaderboard zone labels
	let zoneNames: Map<string, string> | null = $derived.by(() => {
		if (!liveSeed?.graph_json) return null;
		const graph = parseDagGraph(liveSeed.graph_json);
		const map = new Map<string, string>();
		for (const node of graph.nodes) {
			map.set(node.id, node.displayName);
		}
		return map;
	});

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

	// Wall-clock elapsed timer based on server's started_at timestamp
	let startedAt = $derived(liveRace?.started_at ?? initialRace.started_at);

	let elapsedSeconds = $derived.by(() => {
		if (raceStatus !== 'running' || !startedAt) return 0;
		return Math.max(0, Math.floor((now - new Date(startedAt).getTime()) / 1000));
	});

	$effect(() => {
		if (raceStatus !== 'running' || !startedAt) return;

		const interval = setInterval(() => {
			now = Date.now();
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

	let myParticipant = $derived(
		auth.user
			? initialRace.participants.find((p) => p.user.id === auth.user?.id)
			: undefined
	);

	let myWsParticipantId = $derived.by(() => {
		if (!myParticipant) return null;
		const wsP = raceStore.participants.find(
			(p) => p.twitch_username === myParticipant.user.twitch_username,
		);
		return wsP?.id ?? null;
	});

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleString();
	}

	async function handleParticipantAdded() {
		showInviteSearch = false;
		initialRace = await fetchRace(initialRace.id);
	}

	async function handleRemoveParticipant(participantId: string, username: string) {
		if (!confirm(`Remove ${username} from this race?`)) return;
		try {
			await removeParticipant(initialRace.id, participantId);
			initialRace = await fetchRace(initialRace.id);
		} catch (e) {
			console.error('Failed to remove participant:', e);
		}
	}

	async function handleRevokeInvite(inviteId: string, username: string) {
		if (!confirm(`Revoke invite for ${username}?`)) return;
		try {
			await deleteInvite(initialRace.id, inviteId);
			initialRace = await fetchRace(initialRace.id);
		} catch (e) {
			console.error('Failed to revoke invite:', e);
		}
	}

	function handleRaceUpdated(updated: RaceDetail) {
		initialRace = updated;
	}
</script>

<svelte:head>
	<title>{raceName} - SpeedFog Racing</title>
</svelte:head>

<div class="race-page">
	<aside class="sidebar">
		{#if raceStatus === 'finished'}
			<div class="sidebar-section">
				<Leaderboard participants={raceStore.leaderboard} {totalLayers} mode="finished" {zoneNames} />
			</div>

			<CasterList casters={initialRace.casters} />

			{#if isOrganizer}
				<RaceControls
					race={initialRace}
					{raceStatus}
					onRaceUpdated={handleRaceUpdated}
				/>
			{/if}
		{:else if raceStatus === 'running'}
			<div class="sidebar-section">
				<Leaderboard participants={raceStore.leaderboard} {totalLayers} {zoneNames} />
			</div>

			<CasterList casters={initialRace.casters} />

			{#if isOrganizer}
				<RaceControls
					race={initialRace}
					{raceStatus}
					onRaceUpdated={handleRaceUpdated}
				/>
			{/if}
		{:else}
			<div class="sidebar-section">
				<h2>Participants ({mergedParticipants.length})</h2>
				<div class="participant-list">
					{#each mergedParticipants as mp (mp.id)}
						<ParticipantCard
							participant={mp}
							liveStatus={mp.liveStatus}
							isOrganizer={mp.user.id === initialRace.organizer.id}
							isCurrentUser={auth.user?.id === mp.user.id}
							canRemove={isOrganizer && mp.user.id !== initialRace.organizer.id}
							onRemove={() =>
								handleRemoveParticipant(mp.id, mp.user.twitch_username)}
							canDownload={initialRace.seed_total_layers != null}
							{downloading}
							onDownload={handleDownload}
							{downloadError}
						/>
					{/each}
				</div>

				{#if initialRace.pending_invites.length > 0}
					<div class="invite-list">
						{#each initialRace.pending_invites as invite (invite.id)}
							<InviteCard
								{invite}
								canRemove={isOrganizer}
								onRemove={() =>
									handleRevokeInvite(invite.id, invite.twitch_username)}
							/>
						{/each}
					</div>
				{/if}

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
						<button class="invite-btn" onclick={() => (showInviteSearch = true)}>
							+ Invite
						</button>
					{/if}
				{/if}
			</div>

			<CasterList
				casters={initialRace.casters}
				editable={isOrganizer}
				raceId={initialRace.id}
				onRaceUpdated={handleRaceUpdated}
			/>

			{#if isOrganizer}
				<RaceControls
					race={initialRace}
					{raceStatus}
					onRaceUpdated={handleRaceUpdated}
				/>
			{/if}
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
				<ShareButtons />
				<RaceStatus status={raceStatus} />
				{#if raceStatus === 'running'}
					<span class="elapsed-clock">{formatElapsed(elapsedSeconds)}</span>
				{/if}
			</div>
		</header>

		{#if liveSeed?.graph_json && raceStatus === 'running'}
			{#if myWsParticipantId}
				<MetroDagProgressive
					graphJson={liveSeed.graph_json}
					participants={raceStore.participants}
					myParticipantId={myWsParticipantId}
				/>
			{:else}
				<MetroDagLive graphJson={liveSeed.graph_json} participants={raceStore.participants} />
			{/if}
		{:else if liveSeed?.graph_json && raceStatus === 'finished'}
			<Podium participants={raceStore.leaderboard} />
			<MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} />
			<RaceStats participants={raceStore.leaderboard} />
		{:else if liveSeed?.graph_json}
			<MetroDag graphJson={liveSeed.graph_json} />
		{:else if totalNodes && totalPaths && totalLayers}
			<MetroDagBlurred
				{totalLayers}
				{totalNodes}
				{totalPaths}
			/>
		{:else if totalLayers}
			<div class="dag-placeholder">
				<p class="dag-note">DAG hidden until race starts</p>
			</div>
		{/if}

		<div class="race-info">
			<div class="info-grid">
				<div class="info-item">
					<span class="label">Participants</span>
					<span class="value">{mergedParticipants.length}</span>
				</div>
				<div class="info-item">
					<span class="label">Created</span>
					<span class="value">{formatDate(initialRace.created_at)}</span>
				</div>
				{#if initialRace.started_at}
					<div class="info-item">
						<span class="label">Started</span>
						<span class="value">{formatDate(initialRace.started_at)}</span>
					</div>
				{/if}
			</div>
		</div>

		{#if initialRace.pool_config}
			<PoolSettingsCard
				poolName={initialRace.pool_name || 'standard'}
				poolConfig={initialRace.pool_config}
			/>
		{/if}

		{#if myParticipant && initialRace.seed_total_layers != null}
			<div class="download-section">
				<button class="btn btn-secondary" onclick={handleDownload} disabled={downloading}>
					{downloading ? 'Preparing...' : 'Download Race Package'}
				</button>
				{#if downloadError}
					<span class="download-error">{downloadError}</span>
				{/if}
			</div>
		{/if}
	</main>
</div>

<style>
	.race-page {
		display: flex;
		flex: 1;
		min-height: 0;
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

	.invite-list {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		margin-top: 0.5rem;
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

	.download-section {
		display: flex;
		gap: 1rem;
		align-items: center;
	}

	.download-error {
		color: var(--color-danger);
		font-size: 0.9rem;
	}

	@media (max-width: 768px) {
		.race-page {
			flex-direction: column;
		}

		.sidebar {
			width: 100%;
			border-right: none;
			border-bottom: 1px solid var(--color-border);
			padding: 1rem;
		}

		.main-content {
			padding: 1rem;
		}

		.race-header {
			flex-direction: column;
			gap: 0.5rem;
		}

		.race-header h1 {
			font-size: var(--font-size-xl);
		}

		.info-grid {
			grid-template-columns: 1fr 1fr;
		}
	}
</style>
