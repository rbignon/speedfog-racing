<script lang="ts">
	import { untrack } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { raceStore } from '$lib/stores/race.svelte';
	import { computePublicAccess, computePublicLockedReason } from '$lib/public-chat-access';
	import {
		abandonRace,
		downloadMySeedPack,
		fetchDailyByDate,
		getTwitchLoginUrl,
		joinRace,
		type ParticipantStatus as ApiParticipantStatus,
		type RaceDetail,
		type RaceStatus as ApiRaceStatus
	} from '$lib/api';
	import { currentUserParticipant, dailyPathForDate, dailyTheme, dailyTitle } from '$lib/daily';
	import { MetroDagFull, MetroDagProgressive } from '$lib/dag';
	import Leaderboard from '$lib/components/Leaderboard.svelte';
	import SpectatorCount from '$lib/components/SpectatorCount.svelte';
	import RaceControls from '$lib/components/RaceControls.svelte';
	import RaceStats from '$lib/components/RaceStats.svelte';
	import RaceHighlights from '$lib/components/RaceHighlights.svelte';
	import Podium from '$lib/components/Podium.svelte';
	import PoolSettingsCard from '$lib/components/PoolSettingsCard.svelte';
	import ShareButtons from '$lib/components/ShareButtons.svelte';
	import ChatSidebar from '$lib/components/ChatSidebar.svelte';
	import ConfirmModal from '$lib/components/ConfirmModal.svelte';
	import DownloadModal from '$lib/components/DownloadModal.svelte';

	let { data } = $props();
	let initialRace: RaceDetail = $state(untrack(() => data.race));
	let now = $state(Date.now());
	let showDownloadModal = $state(false);
	let downloading = $state(false);
	let downloadError = $state<string | null>(null);
	let joining = $state(false);
	let joinError = $state<string | null>(null);
	let showAbandonConfirm = $state(false);
	let abandoning = $state(false);
	let abandonError = $state<string | null>(null);
	let chatCollapsed = $state(typeof window !== 'undefined' ? window.innerWidth < 1600 : true);
	let chatActiveTab = $state<'participants' | 'public'>('participants');

	$effect(() => {
		initialRace = data.race;
	});

	let raceStatus = $derived(raceStore.race?.status ?? initialRace.status);
	let raceEndsAt = $derived(raceStore.race?.race_ends_at ?? initialRace.race_ends_at);
	let dailyEnded = $derived(
		raceEndsAt ? new Date(raceEndsAt).getTime() <= now : raceStatus === 'finished'
	);
	let myParticipant = $derived(currentUserParticipant(initialRace, auth.user?.id));
	let myWsParticipant = $derived(
		raceStore.participants.find((p) => p.id === myParticipant?.id) ?? null
	);
	let myParticipantStatus = $derived(myWsParticipant?.status ?? myParticipant?.status ?? null);
	let myParticipantFinished = $derived(
		myParticipantStatus === 'finished' || myParticipantStatus === 'abandoned'
	);
	// The daily has no organizer/caster surface, so participants access is
	// purely "do you have a participant row?" plus the admin override.
	let hasParticipantsAccess = $derived(auth.isAdmin || !!myParticipant);
	let isParticipantPlaying = $derived(
		!!myParticipant && raceStatus === 'running' && !myParticipantFinished
	);
	let canShowFullDag = $derived(
		dailyEnded || myParticipantStatus === 'finished' || myParticipantStatus === 'abandoned'
	);
	let canShowProgressiveDag = $derived(
		myParticipantStatus === 'registered' ||
			myParticipantStatus === 'ready' ||
			myParticipantStatus === 'playing'
	);
	let canAbandon = $derived(
		raceStatus === 'running' &&
			!!myParticipant &&
			(myParticipantStatus === 'playing' ||
				myParticipantStatus === 'ready' ||
				myParticipantStatus === 'registered')
	);
	let graphJson = $derived(raceStore.seed?.graph_json ?? null);
	let countdownLabel = $derived.by(() => {
		if (!raceEndsAt) return 'Closes today';
		const remainingMs = Math.max(0, new Date(raceEndsAt).getTime() - now);
		const hours = Math.floor(remainingMs / 3_600_000);
		const minutes = Math.floor((remainingMs % 3_600_000) / 60_000);
		return `Closes in ${hours}h ${minutes}m`;
	});
	let publicAccessInputs = $derived({
		raceStatus: raceStatus as ApiRaceStatus,
		registrationClosesAt: initialRace.registration_closes_at,
		participantStatus: myParticipantStatus as ApiParticipantStatus | null,
		now: new Date(now)
	});
	let publicAccess = $derived(computePublicAccess(publicAccessInputs));
	let publicLockedReason = $derived(computePublicLockedReason(publicAccessInputs));
	let effectiveActiveTab = $derived(hasParticipantsAccess ? chatActiveTab : 'public');
	let canSendChat = $derived(
		effectiveActiveTab === 'participants'
			? hasParticipantsAccess
			: auth.isLoggedIn && publicAccess === 'readable' && !isParticipantPlaying
	);
	let showChatSidebar = $derived(auth.isLoggedIn || publicAccess === 'readable');

	// Pull public chat history when local access transitions from locked to
	// readable (e.g. the viewer's run just transitioned to FINISHED, or
	// registration window closed). The server already shipped history at
	// auth time when we were eligible; this re-pulls only on the lift.
	let prevPublicAccess = $state<'locked' | 'readable' | null>(null);
	$effect(() => {
		const current = publicAccess;
		if (prevPublicAccess === 'locked' && current === 'readable') {
			raceStore.send({ type: 'request_chat_history', channel: 'public' });
		}
		prevPublicAccess = current;
	});

	$effect(() => {
		if (!auth.initialized) return;
		raceStore.connect(initialRace.id);
		return () => raceStore.disconnect();
	});

	$effect(() => {
		const timer = setInterval(() => (now = Date.now()), 1000);
		return () => clearInterval(timer);
	});

	async function handlePlayNow() {
		if (!auth.isLoggedIn) {
			goto(getTwitchLoginUrl());
			return;
		}
		joining = true;
		joinError = null;
		try {
			await joinRace(initialRace.id);
			initialRace = await fetchDailyByDate(initialRace.daily_date!);
			showDownloadModal = true;
		} catch (e) {
			joinError = e instanceof Error ? e.message : 'Failed to join';
		} finally {
			joining = false;
		}
	}

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

	async function handleAbandon() {
		abandoning = true;
		abandonError = null;
		try {
			await abandonRace(initialRace.id);
			initialRace = await fetchDailyByDate(initialRace.daily_date!);
			showAbandonConfirm = false;
		} catch (e) {
			abandonError = e instanceof Error ? e.message : 'Failed to abandon';
		} finally {
			abandoning = false;
		}
	}

	function sendChatMessage(message: string, channel: 'participants' | 'public') {
		raceStore.send({ type: 'chat', channel, message });
	}
</script>

<svelte:head>
	<title>{dailyTitle(initialRace.daily_date!)}</title>
</svelte:head>

<div class="daily-page">
	<aside class="sidebar">
		<div class="sidebar-section">
			<Leaderboard
				participants={raceStore.leaderboard}
				totalLayers={initialRace.seed_total_layers ?? 0}
				mode={dailyEnded ? 'finished' : 'running'}
			/>
		</div>

		{#if canAbandon}
			<div class="abandon-section">
				<button class="abandon-btn" onclick={() => (showAbandonConfirm = true)}>
					Rage quit
				</button>
				{#if abandonError}
					<p class="abandon-error">{abandonError}</p>
				{/if}
			</div>
		{/if}

		{#if myParticipant}
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
				{downloading ? 'Preparing...' : 'Download Daily Seed Pack'}
			</button>
		{/if}

		{#if data.recent.length > 0}
			<section class="recent-dailies">
				<h2>Recent Daily Seeds</h2>
				<ul>
					{#each data.recent as race (race.id)}
						<li>
							<a href={dailyPathForDate(race.daily_date!)}>
								<span>{race.daily_date}</span>
								<span class="theme">· {dailyTheme(race)}</span>
							</a>
						</li>
					{/each}
				</ul>
			</section>
		{/if}

		<SpectatorCount count={raceStore.spectatorCount} />
	</aside>

	<main class="main-content">
		<header class="daily-header">
			<div class="daily-title">
				<h1>{dailyTitle(initialRace.daily_date!)}</h1>
				<p>{dailyTheme(initialRace)}</p>
			</div>
			<div class="daily-meta-right">
				<ShareButtons />
				<span class="daily-pill" class:ended={dailyEnded}>
					{dailyEnded ? 'Ended' : countdownLabel}
				</span>
			</div>
		</header>

		<div class="dag-wrapper">
			{#if !myParticipant && !dailyEnded}
				<button class="dag-placeholder play-now-cta" onclick={handlePlayNow} disabled={joining}>
					<span class="play-now-label">{joining ? 'Joining...' : 'Play now'}</span>
					{#if joinError}
						<span class="play-now-error">{joinError}</span>
					{/if}
				</button>
			{:else if graphJson && canShowFullDag}
				<MetroDagFull {graphJson} participants={raceStore.leaderboard} {raceStatus} />
			{:else if graphJson && canShowProgressiveDag}
				<MetroDagProgressive
					{graphJson}
					participants={raceStore.participants}
					myParticipantId={myWsParticipant?.id ?? ''}
				/>
			{:else}
				<div class="dag-placeholder">
					<p class="dag-note">Loading map...</p>
				</div>
			{/if}
		</div>

		{#if dailyEnded}
			<Podium participants={raceStore.leaderboard} />
		{/if}

		{#if dailyEnded || myParticipantStatus === 'finished'}
			<RaceStats participants={raceStore.leaderboard} />
			{#if graphJson}
				<RaceHighlights
					participants={raceStore.leaderboard}
					{graphJson}
					myParticipantId={myWsParticipant?.id}
					onzoneclick={() => {}}
				/>
			{/if}
		{/if}

		{#if auth.isAdmin}
			<RaceControls
				race={initialRace}
				{raceStatus}
				onRaceUpdated={(race) => (initialRace = race)}
				onDeleteRace={() => goto('/daily')}
			/>
		{/if}

		{#if initialRace.pool_name && initialRace.pool_config}
			<PoolSettingsCard
				poolName={initialRace.pool_name}
				poolConfig={initialRace.pool_config}
			/>
		{/if}
	</main>

	{#if showChatSidebar}
		<ChatSidebar
			messagesParticipants={raceStore.chatMessagesParticipants}
			messagesPublic={raceStore.chatMessagesPublic}
			canSend={canSendChat}
			collapsed={chatCollapsed}
			participantsAccess={hasParticipantsAccess}
			{publicAccess}
			{publicLockedReason}
			activeTab={effectiveActiveTab}
			historyVersion={raceStore.chatHistoryVersion}
			onSend={sendChatMessage}
			onToggle={() => (chatCollapsed = !chatCollapsed)}
			onTabChange={(tab) => (chatActiveTab = tab)}
		/>
	{/if}
</div>

{#if showDownloadModal}
	<DownloadModal
		onClose={() => (showDownloadModal = false)}
		onDownload={handleDownload}
		{downloading}
		error={downloadError}
		actionLabel="Download Daily Seed Pack"
	/>
{/if}

{#if showAbandonConfirm}
	<ConfirmModal
		title="Rage Quit"
		message="Are you sure? This is irreversible."
		confirmLabel="Rage quit"
		danger
		loading={abandoning}
		onConfirm={handleAbandon}
		onCancel={() => (showAbandonConfirm = false)}
	/>
{/if}

<style>
	.daily-page {
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
		gap: 1rem;
		min-height: 0;
	}

	.sidebar-section {
		flex: 1;
		display: flex;
		flex-direction: column;
		overflow-y: auto;
		min-height: 0;
	}

	.abandon-section {
		padding-top: 0.75rem;
		border-top: 1px solid var(--color-border);
	}

	/* Intentional departure from flat design charter:
	   skeuomorphic "big red button" for dramatic effect. Mirrors /race/[id]. */
	.abandon-btn {
		width: 100%;
		padding: 0.75rem 1rem;
		border: none;
		border-radius: var(--radius-md);
		background: radial-gradient(
			ellipse at 50% 35%,
			#f87171 0%,
			var(--color-danger-dark, #dc2626) 50%,
			#991b1b 100%
		);
		color: #fff;
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		font-weight: 700;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		text-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
		cursor: pointer;
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.15),
			0 4px 0 #7f1d1d,
			0 5px 8px rgba(0, 0, 0, 0.4),
			0 0 20px rgba(239, 68, 68, 0.3);
		transition: all 0.1s ease;
	}

	.abandon-btn:hover {
		background: radial-gradient(
			ellipse at 50% 35%,
			#fca5a5 0%,
			var(--color-danger, #ef4444) 50%,
			#b91c1c 100%
		);
		box-shadow:
			inset 0 1px 0 rgba(255, 255, 255, 0.2),
			0 4px 0 #7f1d1d,
			0 5px 8px rgba(0, 0, 0, 0.4),
			0 0 28px rgba(239, 68, 68, 0.45);
	}

	.abandon-btn:active {
		background: radial-gradient(
			ellipse at 50% 55%,
			var(--color-danger-dark, #dc2626) 0%,
			#b91c1c 50%,
			#7f1d1d 100%
		);
		transform: translateY(3px);
		box-shadow:
			inset 0 2px 3px rgba(0, 0, 0, 0.3),
			0 1px 0 #7f1d1d,
			0 2px 4px rgba(0, 0, 0, 0.3),
			0 0 15px rgba(239, 68, 68, 0.2);
	}

	.abandon-btn:focus-visible {
		outline: 2px solid var(--color-danger, #ef4444);
		outline-offset: 2px;
	}

	.abandon-error {
		margin: 0.5rem 0 0;
		color: var(--color-danger, #ef4444);
		font-size: var(--font-size-sm);
	}

	.sidebar-download-btn {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		padding: 0.65rem 1rem;
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

	.recent-dailies h2 {
		margin: 0 0 0.5rem;
		font-size: var(--font-size-base);
	}

	.recent-dailies ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.recent-dailies a {
		color: var(--color-text-secondary);
		text-decoration: none;
		font-size: var(--font-size-sm);
	}

	.recent-dailies a:hover {
		color: var(--color-purple);
	}

	.recent-dailies .theme {
		color: var(--color-text-disabled);
		margin-left: 0.25rem;
	}

	.main-content {
		flex: 1;
		padding: 2rem;
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
		overflow-y: auto;
		min-width: 0;
	}

	.daily-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 1rem;
		flex-wrap: wrap;
	}

	.daily-title h1 {
		margin: 0;
		color: var(--color-text);
		font-size: var(--font-size-2xl);
		font-weight: 600;
	}

	.daily-title p {
		margin: 0.25rem 0 0;
		color: var(--color-text-secondary);
	}

	.daily-meta-right {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.daily-pill {
		padding: 0.25rem 0.6rem;
		border: 1px solid var(--color-success);
		color: var(--color-success);
		border-radius: var(--radius-sm);
		font-size: var(--font-size-sm);
	}

	.daily-pill.ended {
		border-color: var(--color-text-disabled);
		color: var(--color-text-disabled);
	}

	.dag-wrapper {
		position: relative;
	}

	/* Match the race page's DAG sizing: ZoomableSvg ships with a 200px
	   minimum but our layout has the room for 400. Scoped to .daily-page
	   so other surfaces (overlays, dashboards) keep their own defaults. */
	:global(.daily-page .zoomable-container) {
		min-height: 400px;
	}

	:global(.daily-page .zoomable-container svg) {
		min-height: 400px;
	}

	.dag-placeholder {
		background: var(--color-surface);
		border: 2px dashed var(--color-border);
		border-radius: var(--radius-lg);
		display: flex;
		align-items: center;
		justify-content: center;
		min-height: 400px;
	}

	.dag-note {
		color: var(--color-text-disabled);
		font-size: 0.85rem;
		font-style: italic;
		margin: 0;
	}

	/* The Play now CTA reuses .dag-placeholder's box but adopts a
	   "button label" type ramp (uppercase, letter-spaced, muted) so it
	   reads differently from the H1, plus a slightly elevated surface
	   so it stands out from the other cards on the page. */
	.play-now-cta {
		flex-direction: column;
		gap: 0.5rem;
		width: 100%;
		text-align: center;
		background: var(--color-surface-elevated);
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		font-family: inherit;
		font-size: var(--font-size-lg);
		font-weight: 600;
		letter-spacing: 0.18em;
		text-transform: uppercase;
		cursor: pointer;
		transition:
			background var(--transition),
			color var(--transition),
			border-color var(--transition);
	}

	.play-now-cta:hover:not(:disabled) {
		border-color: var(--color-purple);
		color: var(--color-purple-hover);
		background: rgba(139, 92, 246, 0.1);
	}

	.play-now-cta:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.play-now-error {
		font-size: var(--font-size-sm);
		font-weight: 400;
		color: var(--color-danger);
	}

	@media (max-width: 768px) {
		.daily-page {
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

		.daily-header {
			flex-direction: column;
			gap: 0.5rem;
		}
	}
</style>
