<script lang="ts">
	import { untrack } from 'svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import { getEffectiveLocale } from '$lib/stores/locale.svelte';
	import { raceStore } from '$lib/stores/race.svelte';
	import Leaderboard from '$lib/components/Leaderboard.svelte';
	import RaceStatus from '$lib/components/RaceStatus.svelte';

	import SpectatorCount from '$lib/components/SpectatorCount.svelte';
	import ParticipantCard from '$lib/components/ParticipantCard.svelte';
	import InviteCard from '$lib/components/InviteCard.svelte';
	import ParticipantSearch from '$lib/components/ParticipantSearch.svelte';
	import CasterList from '$lib/components/CasterList.svelte';
	import WatchLive from '$lib/components/WatchLive.svelte';
	import RaceControls from '$lib/components/RaceControls.svelte';
	import Podium from '$lib/components/Podium.svelte';
	import PoolSettingsCard from '$lib/components/PoolSettingsCard.svelte';
	import RaceStats from '$lib/components/RaceStats.svelte';
	import RaceHighlights from '$lib/components/RaceHighlights.svelte';
	import ShareButtons from '$lib/components/ShareButtons.svelte';
	import ObsOverlayModal from '$lib/components/ObsOverlayModal.svelte';
	import DownloadModal from '$lib/components/DownloadModal.svelte';
	import DateTimePicker from '$lib/components/DateTimePicker.svelte';
	import { MetroDag, MetroDagBlurred, MetroDagProgressive, MetroDagFull } from '$lib/dag';
	import { parseDagGraph } from '$lib/dag/types';
	import {
		downloadMySeedPack,
		removeParticipant,
		deleteInvite,
		fetchRace,
		updateRace,
		joinRace,
		leaveRace,
		type RaceDetail
	} from '$lib/api';
	import { formatScheduledTime } from '$lib/utils/time';

	let downloading = $state(false);
	let downloadError = $state<string | null>(null);
	let showInviteSearch = $state(false);
	let joining = $state(false);
	let leaving = $state(false);
	let joinLeaveError = $state<string | null>(null);
	let now = $state(Date.now());
	let editingSchedule = $state(false);
	let scheduleInput = $state('');
	let scheduleError = $state<string | null>(null);
	let scheduleSaving = $state(false);
	let selectedParticipantIds = $state<Set<string>>(new Set());
	let showDownloadModal = $state(false);

	async function handleDownload() {
		downloading = true;
		downloadError = null;
		try {
			await downloadMySeedPack(initialRace.id);
			showDownloadModal = false;
		} catch (e) {
			downloadError = e instanceof Error ? e.message : 'Download failed';
		} finally {
			downloading = false;
		}
	}

	let { data } = $props();

	// untrack: initial snapshot only; the $effect below handles route-change updates
	let initialRace: RaceDetail = $state(untrack(() => data.race));

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
	let seedsReleased = $derived(
		(liveRace?.seeds_released_at ?? initialRace.seeds_released_at) !== null
	);

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
		if (!auth.initialized) return;

		const locale = untrack(() => getEffectiveLocale());
		raceStore.connect(initialRace.id, locale);

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

	let showGo = $state(false);
	let previousRaceStatus: string | null = null;

	$effect(() => {
		const wasNotRunning = previousRaceStatus !== null && previousRaceStatus !== 'running';
		previousRaceStatus = raceStatus;
		clearSelection();
		if (raceStatus === 'running' && wasNotRunning) {
			showGo = true;
			const timer = setTimeout(() => {
				showGo = false;
			}, 3000);
			return () => clearTimeout(timer);
		} else {
			showGo = false;
		}
	});

	function formatElapsed(totalSeconds: number): string {
		const h = Math.floor(totalSeconds / 3600);
		const m = Math.floor((totalSeconds % 3600) / 60);
		const s = totalSeconds % 60;
		return `${h.toString().padStart(2, '0')}:${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
	}

	let isOrganizer = $derived(auth.user?.id === initialRace.organizer.id);
	let isCaster = $derived(
		auth.user ? initialRace.casters.some((c) => c.user.id === auth.user?.id) : false
	);
	let showObsModal = $state(false);

	let myParticipant = $derived(
		auth.user ? initialRace.participants.find((p) => p.user.id === auth.user?.id) : undefined
	);

	let myWsParticipant = $derived.by(() => {
		if (!myParticipant) return null;
		return (
			raceStore.participants.find(
				(p) => p.twitch_username === myParticipant.user.twitch_username
			) ?? null
		);
	});

	let myWsParticipantId = $derived(myWsParticipant?.id ?? null);
	let myParticipantFinished = $derived(myWsParticipant?.status === 'finished');

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

	let canJoin = $derived(
		initialRace.open_registration &&
			raceStatus === 'setup' &&
			auth.isLoggedIn &&
			!myParticipant &&
			!isCaster &&
			!isOrganizer &&
			(initialRace.max_participants === null ||
				mergedParticipants.length < initialRace.max_participants)
	);

	let raceFull = $derived(
		initialRace.open_registration &&
			initialRace.max_participants !== null &&
			mergedParticipants.length >= initialRace.max_participants
	);

	let canLeave = $derived(raceStatus === 'setup' && !!myParticipant && !isOrganizer);

	async function handleJoin() {
		joining = true;
		joinLeaveError = null;
		try {
			await joinRace(initialRace.id);
			initialRace = await fetchRace(initialRace.id);
		} catch (e) {
			joinLeaveError = e instanceof Error ? e.message : 'Failed to join';
		} finally {
			joining = false;
		}
	}

	async function handleLeave() {
		leaving = true;
		joinLeaveError = null;
		try {
			await leaveRace(initialRace.id);
			initialRace = await fetchRace(initialRace.id);
		} catch (e) {
			joinLeaveError = e instanceof Error ? e.message : 'Failed to leave';
		} finally {
			leaving = false;
		}
	}

	function startEditSchedule() {
		scheduleInput = initialRace.scheduled_at ?? '';
		scheduleError = null;
		editingSchedule = true;
	}

	async function saveSchedule() {
		scheduleSaving = true;
		scheduleError = null;
		try {
			const scheduled = scheduleInput || null;
			await updateRace(initialRace.id, { scheduled_at: scheduled });
			initialRace = await fetchRace(initialRace.id);
			editingSchedule = false;
		} catch (e) {
			scheduleError = e instanceof Error ? e.message : 'Failed to update';
		} finally {
			scheduleSaving = false;
		}
	}

	function handleRaceUpdated(updated: RaceDetail) {
		initialRace = updated;
	}

	function handleLeaderboardToggle(id: string, ctrlKey: boolean) {
		if (ctrlKey) {
			const next = new Set(selectedParticipantIds);
			if (next.has(id)) next.delete(id);
			else next.add(id);
			selectedParticipantIds = next;
		} else {
			if (selectedParticipantIds.size === 1 && selectedParticipantIds.has(id)) {
				selectedParticipantIds = new Set();
			} else {
				selectedParticipantIds = new Set([id]);
			}
		}
	}

	function clearSelection() {
		selectedParticipantIds = new Set();
	}

	let togglingVisibility = $state(false);

	async function handleToggleVisibility() {
		togglingVisibility = true;
		try {
			await updateRace(initialRace.id, { is_public: !initialRace.is_public });
			initialRace = await fetchRace(initialRace.id);
		} catch (e) {
			console.error('Failed to toggle visibility:', e);
		} finally {
			togglingVisibility = false;
		}
	}
</script>

<svelte:head>
	<title>{raceName} - SpeedFog Racing</title>
</svelte:head>

<div class="race-page">
	<aside class="sidebar">
		{#if raceStatus === 'finished'}
			<div class="sidebar-section">
				<Leaderboard
					participants={raceStore.leaderboard}
					{totalLayers}
					mode="finished"
					{zoneNames}
					selectedIds={selectedParticipantIds}
					onToggle={handleLeaderboardToggle}
					onClearSelection={clearSelection}
				/>
			</div>

			<CasterList casters={initialRace.casters} />

			{#if isOrganizer}
				<RaceControls race={initialRace} {raceStatus} onRaceUpdated={handleRaceUpdated} />
			{/if}
		{:else if raceStatus === 'running'}
			<WatchLive casters={initialRace.casters} />

			<div class="sidebar-section">
				<Leaderboard
					participants={raceStore.leaderboard}
					{totalLayers}
					zoneNames={myWsParticipantId && !myParticipantFinished ? null : zoneNames}
					selectedIds={selectedParticipantIds}
					onToggle={handleLeaderboardToggle}
					onClearSelection={clearSelection}
				/>
			</div>

			{#if isOrganizer}
				<RaceControls race={initialRace} {raceStatus} onRaceUpdated={handleRaceUpdated} />
			{/if}
		{:else}
			<div class="sidebar-section">
				<h2>
					Participants ({mergedParticipants.length}{#if initialRace.open_registration && initialRace.max_participants}
						/{initialRace.max_participants}{/if})
				</h2>
				<div class="participant-list">
					{#each mergedParticipants as mp (mp.id)}
						<ParticipantCard
							participant={mp}
							liveStatus={mp.liveStatus}
							isOrganizer={mp.user.id === initialRace.organizer.id}
							isCurrentUser={auth.user?.id === mp.user.id}
							canRemove={isOrganizer && mp.user.id !== initialRace.organizer.id}
							onRemove={() => handleRemoveParticipant(mp.id, mp.user.twitch_username)}
						/>
					{/each}

					{#if initialRace.pending_invites.length > 0}
						{#each initialRace.pending_invites as invite (invite.id)}
							<InviteCard
								{invite}
								canRemove={isOrganizer}
								onRemove={() => handleRevokeInvite(invite.id, invite.twitch_username)}
							/>
						{/each}
					{/if}
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

				{#if initialRace.open_registration && raceStatus === 'setup'}
					{#if canJoin}
						<button class="join-btn" onclick={handleJoin} disabled={joining}>
							{joining ? 'Joining...' : 'Join Race'}
						</button>
					{:else if raceFull && !myParticipant}
						<button class="join-btn disabled" disabled> Race Full </button>
					{/if}
					{#if canLeave}
						<button class="leave-btn" onclick={handleLeave} disabled={leaving}>
							{leaving ? 'Leaving...' : 'Leave Race'}
						</button>
					{/if}
					{#if !auth.isLoggedIn}
						<p class="login-hint">
							<a href="/auth/login">Log in</a> to join this race
						</p>
					{/if}
					{#if joinLeaveError}
						<p class="join-leave-error">{joinLeaveError}</p>
					{/if}
				{/if}
			</div>

			{#if myParticipant}
				{#if seedsReleased}
					<button
						class="sidebar-download-btn"
						onclick={() => {
							downloadError = null;
							showDownloadModal = true;
						}}
						disabled={downloading}
					>
						<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
							<path
								d="M8 1v9m0 0L5 7m3 3 3-3M3 13h10"
								stroke="currentColor"
								stroke-width="1.5"
								stroke-linecap="round"
								stroke-linejoin="round"
								fill="none"
							/>
						</svg>
						{downloading ? 'Preparing...' : 'Download Race Package'}
					</button>
				{:else}
					<p class="waiting-seeds">Waiting for seeds...</p>
				{/if}
			{/if}

			<CasterList
				casters={initialRace.casters}
				editable={isOrganizer}
				raceId={initialRace.id}
				onRaceUpdated={handleRaceUpdated}
			/>

			{#if isOrganizer}
				<RaceControls race={initialRace} {raceStatus} onRaceUpdated={handleRaceUpdated} />
			{/if}
		{/if}

		{#if isOrganizer}
			<div class="visibility-toggle">
				<button
					class="btn-toggle-visibility"
					onclick={handleToggleVisibility}
					disabled={togglingVisibility}
				>
					{#if initialRace.is_public}
						<svg
							class="visibility-icon"
							viewBox="0 0 20 20"
							fill="currentColor"
							width="14"
							height="14"
						>
							<path d="M10 12a2 2 0 100-4 2 2 0 000 4z" />
							<path
								fill-rule="evenodd"
								d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z"
								clip-rule="evenodd"
							/>
						</svg>
						Public
					{:else}
						<svg
							class="visibility-icon"
							viewBox="0 0 20 20"
							fill="currentColor"
							width="14"
							height="14"
						>
							<path
								fill-rule="evenodd"
								d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074l-1.78-1.781zm4.261 4.26l1.514 1.515a2.003 2.003 0 012.45 2.45l1.514 1.514a4 4 0 00-5.478-5.478z"
								clip-rule="evenodd"
							/>
							<path
								d="M12.454 16.697L9.75 13.992a4 4 0 01-3.742-3.741L2.335 6.578A9.98 9.98 0 00.458 10c1.274 4.057 5.065 7 9.542 7 .847 0 1.669-.105 2.454-.303z"
							/>
						</svg>
						Private
					{/if}
				</button>
			</div>
		{/if}

		{#if isOrganizer || isCaster || myParticipant}
			<button class="obs-overlay-btn" onclick={() => (showObsModal = true)}> OBS Overlays </button>
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
				{#if !initialRace.is_public}
					<span class="visibility-badge">Private</span>
				{/if}
				{#if initialRace.seed_number}
					<span class="seed-badge">Seed {initialRace.seed_number}</span>
				{/if}
				<RaceStatus status={raceStatus} />
				{#if raceStatus === 'running'}
					<span class="elapsed-clock">{formatElapsed(elapsedSeconds)}</span>
				{/if}
			</div>
		</header>

		{#if showGo}
			<div class="go-banner">GO!</div>
		{/if}

		{#if liveSeed?.graph_json && raceStatus === 'running'}
			{#if myWsParticipantId && !myParticipantFinished}
				<MetroDagProgressive
					graphJson={liveSeed.graph_json}
					participants={raceStore.participants}
					myParticipantId={myWsParticipantId}
				/>
			{:else}
				<MetroDagFull
					graphJson={liveSeed.graph_json}
					participants={raceStore.leaderboard}
					highlightIds={selectedParticipantIds}
				/>
			{/if}
		{:else if liveSeed?.graph_json && raceStatus === 'finished'}
			<Podium participants={raceStore.leaderboard} />
			<MetroDagFull
				graphJson={liveSeed.graph_json}
				participants={raceStore.leaderboard}
				highlightIds={selectedParticipantIds}
			/>
			<RaceStats participants={raceStore.leaderboard} />
			<RaceHighlights participants={raceStore.leaderboard} graphJson={liveSeed.graph_json} />
		{:else if liveSeed?.graph_json && myWsParticipantId}
			<MetroDagProgressive
				graphJson={liveSeed.graph_json}
				participants={raceStore.participants}
				myParticipantId={myWsParticipantId}
			/>
		{:else if liveSeed?.graph_json}
			<MetroDag graphJson={liveSeed.graph_json} />
		{:else if totalNodes && totalPaths && totalLayers}
			<MetroDagBlurred {totalLayers} {totalNodes} {totalPaths} />
		{:else if totalLayers}
			<div class="dag-placeholder">
				<p class="dag-note">DAG hidden until race starts</p>
			</div>
		{/if}

		<div class="race-info">
			<div class="info-grid">
				<div class="info-item">
					<span class="label">Participants</span>
					<span class="value">{mergedParticipants.length}{#if initialRace.open_registration && initialRace.max_participants}
						/{initialRace.max_participants}{/if}</span>
				</div>
				<div class="info-item">
					<span class="label">Created</span>
					<span class="value">{formatDate(initialRace.created_at)}</span>
				</div>
				{#if initialRace.scheduled_at || (isOrganizer && raceStatus === 'setup')}
					<div class="info-item">
						<span class="label">Scheduled</span>
						{#if editingSchedule}
							<div class="schedule-edit">
								<DateTimePicker
									value={scheduleInput}
									onchange={(iso) => (scheduleInput = iso)}
									min={new Date()}
									disabled={scheduleSaving}
								/>
								<div class="schedule-edit-actions">
									<button class="btn-inline" onclick={saveSchedule} disabled={scheduleSaving}>
										{scheduleSaving ? '...' : 'Save'}
									</button>
									<button
										class="btn-inline btn-inline-secondary"
										onclick={() => (editingSchedule = false)}
										disabled={scheduleSaving}
									>
										Cancel
									</button>
								</div>
								{#if scheduleError}
									<span class="schedule-error">{scheduleError}</span>
								{/if}
							</div>
						{:else if initialRace.scheduled_at}
							<span class="value">
								{formatDate(initialRace.scheduled_at)}
								{#if isOrganizer && raceStatus === 'setup'}
									<button class="btn-edit" onclick={startEditSchedule}>Edit</button>
								{/if}
							</span>
						{:else if isOrganizer}
							<button class="btn-edit" onclick={startEditSchedule}>Set time</button>
						{/if}
					</div>
				{/if}
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
	</main>

	{#if showObsModal}
		<ObsOverlayModal raceId={initialRace.id} onClose={() => (showObsModal = false)} />
	{/if}

	{#if showDownloadModal}
		<DownloadModal
			{downloading}
			error={downloadError}
			onClose={() => (showDownloadModal = false)}
			onDownload={handleDownload}
		/>
	{/if}
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
		min-height: 0;
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

	.join-btn {
		margin-top: 0.75rem;
		width: 100%;
		padding: 0.75rem;
		border: 2px dashed var(--color-success, #10b981);
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-success, #10b981);
		font-family: var(--font-family);
		font-size: var(--font-size-base);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition);
	}

	.join-btn:hover:not(:disabled) {
		background: rgba(16, 185, 129, 0.1);
	}

	.join-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.join-btn.disabled {
		border-color: var(--color-border);
		color: var(--color-text-disabled);
		cursor: not-allowed;
		opacity: 0.6;
	}

	.leave-btn {
		margin-top: 0.5rem;
		width: 100%;
		padding: 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text-disabled);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		transition: all var(--transition);
	}

	.leave-btn:hover:not(:disabled) {
		border-color: var(--color-danger, #ef4444);
		color: var(--color-danger, #ef4444);
	}

	.leave-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.login-hint {
		margin: 0.75rem 0 0;
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
		text-align: center;
	}

	.login-hint a {
		color: var(--color-purple);
	}

	.join-leave-error {
		margin: 0.5rem 0 0;
		color: var(--color-danger, #ef4444);
		font-size: var(--font-size-sm);
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
		overflow-y: auto;
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

	.seed-badge {
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: var(--font-size-xs);
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: 0.2rem 0.5rem;
		color: var(--color-text-secondary);
	}

	.schedule-edit {
		display: flex;
		flex-direction: column;
		gap: 0.35rem;
	}

	.schedule-edit-actions {
		display: flex;
		gap: 0.5rem;
	}

	.btn-inline {
		background: none;
		border: none;
		padding: 0;
		color: var(--color-purple);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		font-weight: 500;
	}

	.btn-inline:hover {
		text-decoration: underline;
	}

	.btn-inline:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.btn-inline-secondary {
		color: var(--color-text-disabled);
	}

	.btn-edit {
		background: none;
		border: none;
		padding: 0;
		margin-left: 0.5rem;
		color: var(--color-purple);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
	}

	.btn-edit:hover {
		text-decoration: underline;
	}

	.schedule-error {
		color: var(--color-danger);
		font-size: var(--font-size-xs);
	}

	.waiting-seeds {
		margin: 0;
		padding: 0.75rem;
		text-align: center;
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
		font-style: italic;
	}

	.sidebar-download-btn {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		padding: 0.65rem 1rem;
		margin-top: 0.75rem;
		border: 2px solid var(--color-purple);
		border-radius: var(--radius-sm);
		background: rgba(139, 92, 246, 0.1);
		color: var(--color-purple);
		font-family: var(--font-family);
		font-size: var(--font-size-base);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition);
	}

	.sidebar-download-btn:hover:not(:disabled) {
		background: rgba(139, 92, 246, 0.2);
		border-color: var(--color-purple-hover);
		color: var(--color-purple-hover);
	}

	.sidebar-download-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.obs-overlay-btn {
		width: 100%;
		padding: 0.5rem;
		margin-top: 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		transition: all var(--transition);
	}

	.obs-overlay-btn:hover {
		border-color: var(--color-purple);
		color: var(--color-purple);
	}

	:global(.race-page .zoomable-container) {
		min-height: 500px;
	}

	:global(.race-page .zoomable-container svg) {
		min-height: 500px;
	}

	@media (max-width: 768px) {
		.race-page {
			flex-direction: column;
			flex: initial;
		}

		.sidebar {
			width: 100%;
			border-right: none;
			border-bottom: 1px solid var(--color-border);
			padding: 1rem;
		}

		.main-content {
			padding: 1rem;
			overflow-y: visible;
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

	.go-banner {
		text-align: center;
		font-size: 3rem;
		font-weight: 800;
		color: var(--color-success, #10b981);
		padding: 1rem 0;
		animation: go-fade 3s ease-out forwards;
	}

	@keyframes go-fade {
		0% {
			opacity: 1;
			transform: scale(1.2);
		}
		70% {
			opacity: 1;
			transform: scale(1);
		}
		100% {
			opacity: 0;
			transform: scale(1);
		}
	}

	.visibility-badge {
		font-size: var(--font-size-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 0.15em 0.5em;
		border-radius: var(--radius);
		background: rgba(107, 114, 128, 0.2);
		color: var(--color-text-disabled);
	}

	.visibility-toggle {
		padding-top: 0.75rem;
		border-top: 1px solid var(--color-border);
	}

	.btn-toggle-visibility {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
		background: none;
		border: 1px solid var(--color-border);
		border-radius: var(--radius);
		padding: 0.35rem 0.75rem;
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-xs);
		cursor: pointer;
		transition:
			border-color var(--transition),
			color var(--transition);
	}

	.btn-toggle-visibility:hover {
		border-color: var(--color-text-secondary);
		color: var(--color-text);
	}

	.btn-toggle-visibility:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.visibility-icon {
		width: 14px;
		height: 14px;
	}
</style>
