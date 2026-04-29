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
		leaveRace,
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
	import DownloadModal from '$lib/components/DownloadModal.svelte';

	let { data } = $props();
	let initialRace: RaceDetail = $state(untrack(() => data.race));
	let now = $state(Date.now());
	let showDownloadModal = $state(false);
	let downloading = $state(false);
	let downloadError = $state<string | null>(null);
	let joining = $state(false);
	let joinError = $state<string | null>(null);
	let chatCollapsed = $state(typeof window !== 'undefined' ? window.innerWidth < 1600 : true);
	let chatActiveTab = $state<'participants' | 'public'>('public');

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
	let canShowFullDag = $derived(
		dailyEnded || myParticipantStatus === 'finished' || myParticipantStatus === 'abandoned'
	);
	let canShowProgressiveDag = $derived(
		myParticipantStatus === 'registered' ||
			myParticipantStatus === 'ready' ||
			myParticipantStatus === 'playing'
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

	async function handleLeave() {
		await leaveRace(initialRace.id);
		initialRace = await fetchDailyByDate(initialRace.daily_date!);
	}

	async function handleAbandon() {
		await abandonRace(initialRace.id);
		initialRace = await fetchDailyByDate(initialRace.daily_date!);
	}

	function sendChatMessage(message: string, channel: 'participants' | 'public') {
		raceStore.send({ type: 'chat', channel, message });
	}
</script>

<svelte:head>
	<title>{dailyTitle(initialRace.daily_date!)}</title>
</svelte:head>

<main class="daily-page">
	<aside class="daily-sidebar">
		<div class="daily-meta">
			<strong>{dailyTheme(initialRace)}</strong>
			<span class="pool">{initialRace.pool_name ?? 'Unknown'}</span>
		</div>

		<Leaderboard
			participants={raceStore.leaderboard}
			totalLayers={initialRace.seed_total_layers ?? 0}
			mode={dailyEnded ? 'finished' : 'running'}
		/>

		<div class="daily-actions">
			{#if myParticipant && myParticipantStatus === 'registered'}
				<button class="btn btn-secondary" onclick={handleLeave}>Leave</button>
			{/if}
			{#if myParticipantStatus === 'playing'}
				<button class="btn btn-danger" onclick={handleAbandon}>Rage quit</button>
			{/if}
			{#if myParticipant}
				<button class="btn btn-secondary" onclick={() => (showDownloadModal = true)}>
					Download Daily Seed Pack
				</button>
			{/if}
		</div>

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

	<section class="daily-main">
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
				<button class="play-now-cta" onclick={handlePlayNow} disabled={joining}>
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
				<div class="dag-placeholder">Loading map...</div>
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

		{#if initialRace.pool_name && initialRace.pool_config}
			<PoolSettingsCard
				poolName={initialRace.pool_name}
				poolConfig={initialRace.pool_config}
			/>
		{/if}

		{#if auth.isAdmin}
			<RaceControls
				race={initialRace}
				{raceStatus}
				onRaceUpdated={(race) => (initialRace = race)}
				onDeleteRace={() => goto('/daily')}
			/>
		{/if}
	</section>

	<ChatSidebar
		messagesParticipants={[]}
		messagesPublic={raceStore.chatMessagesPublic}
		canSend={auth.isLoggedIn && publicAccess === 'readable'}
		collapsed={chatCollapsed}
		participantsAccess={false}
		{publicAccess}
		{publicLockedReason}
		showPublicOnly={true}
		activeTab={chatActiveTab}
		historyVersion={raceStore.chatHistoryVersion}
		onSend={sendChatMessage}
		onToggle={() => (chatCollapsed = !chatCollapsed)}
		onTabChange={(tab) => (chatActiveTab = tab)}
	/>
</main>

{#if showDownloadModal}
	<DownloadModal
		onClose={() => (showDownloadModal = false)}
		onDownload={handleDownload}
		{downloading}
		error={downloadError}
		actionLabel="Download Daily Seed Pack"
	/>
{/if}

<style>
	.daily-page {
		display: grid;
		grid-template-columns: 280px 1fr auto;
		gap: 1.5rem;
		padding: 1.5rem 2rem;
		min-height: 100%;
	}

	.daily-sidebar {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.daily-meta {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.daily-meta strong {
		color: var(--color-gold);
	}

	.daily-meta .pool {
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.daily-actions {
		display: flex;
		flex-wrap: wrap;
		gap: 0.5rem;
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

	.daily-main {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
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
		font-size: var(--font-size-xl);
		color: var(--color-gold);
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
		min-height: 320px;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		background: var(--color-surface);
		display: flex;
		align-items: center;
		justify-content: center;
		overflow: hidden;
	}

	.play-now-cta {
		all: unset;
		cursor: pointer;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		padding: 3rem;
		color: var(--color-gold);
		font-size: var(--font-size-xl);
		font-weight: 700;
		width: 100%;
		text-align: center;
	}

	.play-now-cta:hover {
		color: var(--color-gold-hover);
	}

	.play-now-cta:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.play-now-error {
		margin-top: 0.5rem;
		font-size: var(--font-size-sm);
		color: var(--color-danger);
	}

	.dag-placeholder {
		color: var(--color-text-disabled);
	}

	@media (max-width: 1024px) {
		.daily-page {
			grid-template-columns: 1fr;
		}
	}
</style>
