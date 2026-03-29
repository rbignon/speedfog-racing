<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import {
		fetchUserProfile,
		fetchUserActivity,
		fetchUserPoolStats,
		fetchMyRaces,
		fetchTrainingSessions,
		fetchJoinableRaces,
		type UserProfile,
		type UserPoolStats,
		type ActivityItem,
		type Race,
		type TrainingSession,
	} from '$lib/api';
	import { timeAgo, raceDisplayDate } from '$lib/utils/time';
	import { formatIgt } from '$lib/utils/training';
	import { formatPoolName } from '$lib/utils/format';
	import { statusLabel } from '$lib/format';
	import LiveIndicator from '$lib/components/LiveIndicator.svelte';
	import PoolStatsTable from '$lib/components/PoolStatsTable.svelte';
	import RaceCard from '$lib/components/RaceCard.svelte';

	let profile: UserProfile | null = $state(null);
	let poolStats: UserPoolStats | null = $state(null);
	let activity: ActivityItem[] = $state([]);
	let myRaces: Race[] = $state([]);
	let trainingSessions: TrainingSession[] = $state([]);
	let joinableRaces: Race[] = $state([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let fetched = $state(false);

	let activeRaces = $derived(myRaces.filter((r) => r.status !== 'finished'));
	let activeTraining = $derived(trainingSessions.filter((s) => s.status === 'active'));

	// New user detection: no races and no training sessions ever
	let isNewUser = $derived.by(() => {
		const p = profile;
		if (!p) return false;
		return p.stats.race_count + p.stats.training_count === 0;
	});

	// Welcome card dismissal
	const WELCOME_CARD_KEY = 'speedfog_welcome_dismissed';
	let welcomeDismissed = $state(
		typeof localStorage !== 'undefined' && localStorage.getItem(WELCOME_CARD_KEY) === '1',
	);
	let showWelcome = $derived(isNewUser && !welcomeDismissed);

	function dismissWelcome() {
		welcomeDismissed = true;
		localStorage.setItem(WELCOME_CARD_KEY, '1');
	}

	// One-time settings banner
	const SETTINGS_BANNER_KEY = 'speedfog_settings_banner_dismissed';
	let bannerDismissed = $state(
		typeof localStorage !== 'undefined' && localStorage.getItem(SETTINGS_BANNER_KEY) === '1',
	);

	function dismissBanner() {
		bannerDismissed = true;
		localStorage.setItem(SETTINGS_BANNER_KEY, '1');
	}

	// Auth guard + fetch data once auth is ready
	$effect(() => {
		if (!auth.initialized) return;
		if (!auth.isLoggedIn) {
			goto('/');
			return;
		}
		if (fetched || !auth.user) return;
		fetched = true;

		const username = auth.user.twitch_username;
		loading = true;
		error = null;
		Promise.all([
			fetchUserProfile(username),
			fetchUserActivity(username, 0, 20),
			fetchMyRaces(),
			fetchTrainingSessions(),
			fetchUserPoolStats(username),
			fetchJoinableRaces(),
		])
			.then(([p, a, r, t, ps, jr]) => {
				profile = p;
				activity = a.items;
				myRaces = r;
				trainingSessions = t;
				poolStats = ps;
				joinableRaces = jr;
			})
			.catch((e) => {
				console.error('Dashboard fetch error:', e);
				error = 'Failed to load dashboard data.';
			})
			.finally(() => (loading = false));
	});

	function activityLink(item: ActivityItem): string {
		if (item.type === 'training') return `/training/${item.session_id}`;
		return `/race/${item.race_id}`;
	}

	function activityLabel(item: ActivityItem): string {
		if (item.type === 'race_participant') return item.race_name;
		if (item.type === 'race_organizer') return item.race_name;
		if (item.type === 'race_caster') return item.race_name;
		if (item.type === 'training') return item.pool_display_name || formatPoolName(item.pool_name);
		return '';
	}

	function activityBadge(item: ActivityItem): string {
		if (item.type === 'race_participant') {
			if (item.status === 'finished' && item.placement) return placementMedal(item.placement);
			if (item.status === 'finished') return 'Raced';
			if (item.status === 'running') return 'Racing';
			return 'Joined';
		}
		if (item.type === 'race_organizer') return 'Organized';
		if (item.type === 'race_caster') return 'Casted';
		if (item.type === 'training') return 'Solo';
		return '';
	}

	function placementMedal(placement: number): string {
		if (placement === 1) return '1st';
		if (placement === 2) return '2nd';
		if (placement === 3) return '3rd';
		return `${placement}th`;
	}

	function activeRaceRole(race: Race): string {
		const isOrganizer = race.organizer.id === auth.user?.id;
		const isParticipant = race.my_igt_ms != null || race.my_death_count != null;
		if (isParticipant) return 'Participating';
		if (isOrganizer) return 'Organizing';
		return '';
	}
</script>

<svelte:head>
	<title>Dashboard - SpeedFog Racing</title>
</svelte:head>

<main class="dashboard">
	{#if loading}
		<div class="loading-state">
			<p>Loading dashboard...</p>
		</div>
	{:else if error}
		<div class="error-state">
			<p>{error}</p>
			<button class="btn btn-secondary" onclick={() => location.reload()}>Retry</button>
		</div>
	{:else}
		<!-- Settings banner (one-time) -->
		{#if !bannerDismissed}
			<div class="settings-banner">
				<div class="settings-banner-content">
					<span class="settings-banner-icon">&#9881;</span>
					<p>
						You can customize your experience in
						<a href="/settings">Settings</a>: adjust the in-game
						<strong>overlay font size</strong> and choose your
						<strong>language</strong> for zone names and exit descriptions.
					</p>
				</div>
				<button class="settings-banner-close" onclick={dismissBanner} aria-label="Dismiss">&times;</button>
			</div>
		{/if}

		<!-- Welcome Card (new users) OR Stats Section (returning users) -->
		{#if showWelcome}
			<section class="welcome-section">
				<div class="welcome-card">
					<div class="welcome-header">
						<div>
							<h2 class="welcome-title">Get started</h2>
							<p class="welcome-subtitle">Play your first seed in minutes. No setup, no configuration.</p>
						</div>
						<button class="welcome-dismiss" onclick={dismissWelcome} aria-label="Dismiss">Dismiss</button>
					</div>
					<div class="welcome-steps">
						<div class="welcome-step">
							<div class="welcome-step-icon">
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><circle cx="12" cy="12" r="10"/><polygon points="10 8 16 12 10 16 10 8" fill="currentColor" stroke="none"/></svg>
							</div>
							<div class="welcome-step-label">1. Start a solo</div>
							<div class="welcome-step-desc">Pick a seed pool and generate your run</div>
						</div>
						<div class="welcome-step">
							<div class="welcome-step-icon">
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
							</div>
							<div class="welcome-step-label">2. Download</div>
							<div class="welcome-step-desc">Get the seed pack, a single zip file</div>
						</div>
						<div class="welcome-step">
							<div class="welcome-step-icon">
								<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" width="20" height="20"><rect x="2" y="3" width="20" height="14" rx="2" ry="2"/><line x1="8" y1="21" x2="16" y2="21"/><line x1="12" y1="17" x2="12" y2="21"/></svg>
							</div>
							<div class="welcome-step-label">3. Run and play</div>
							<div class="welcome-step-desc">Launch the bat file, done</div>
						</div>
					</div>
					<div class="welcome-actions">
						<a href="/training" class="btn btn-primary">Play Solo</a>
						<a href="/help" class="welcome-link">How it works &rarr;</a>
					</div>
				</div>
			</section>
		{:else if profile}
			<section class="stats-section">
				<div class="stats-grid">
					<div class="stat-card">
						<span class="stat-value">{profile.stats.race_count}</span>
						<span class="stat-label">Races</span>
					</div>
					<div class="stat-card">
						<span class="stat-value">{profile.stats.training_count}</span>
						<span class="stat-label">Solo</span>
					</div>
					<div class="stat-card">
						<span class="stat-value">{profile.stats.organized_count}</span>
						<span class="stat-label">Organized</span>
					</div>
					<div class="stat-card">
						<span class="stat-value">{profile.stats.casted_count}</span>
						<span class="stat-label">Casted</span>
					</div>
				</div>
			</section>
		{/if}

		<!-- Active Now Section (hidden when empty) -->
		{#if activeRaces.length > 0 || activeTraining.length > 0}
			<section class="active-section">
				<h2>Active Now</h2>
				<div class="active-cards">
					{#each activeRaces as race}
						{@const overflowCount = Math.max(0, race.participant_count - race.participant_previews.length)}
						{@const relativeTime = raceDisplayDate(race)}
						<a href="/race/{race.id}" class="active-card border-{race.status === 'running' ? 'running' : 'setup'}">
							<div class="active-card-header">
								<div class="active-title">
									{#if race.status === 'running'}
										<LiveIndicator dotOnly />
									{/if}
									<span class="active-name">{race.name}</span>
								</div>
								<div class="active-badges">
									{#if activeRaceRole(race)}
										<span class="badge badge-role">{activeRaceRole(race)}</span>
									{/if}
									<span class="badge badge-{race.status}">{statusLabel(race.status)}</span>
								</div>
							</div>
							{#if race.participant_previews.length > 0}
								<div class="avatar-row">
									<div class="avatar-stack">
										{#each race.participant_previews as user}
											{#if user.twitch_avatar_url}
												<img src={user.twitch_avatar_url} alt={user.twitch_display_name || user.twitch_username} class="avatar" />
											{:else}
												<span class="avatar avatar-placeholder">{(user.twitch_display_name || user.twitch_username).charAt(0).toUpperCase()}</span>
											{/if}
										{/each}
										{#if overflowCount > 0}
											<span class="avatar avatar-overflow">+{overflowCount}</span>
										{/if}
									</div>
									<span class="relative-time">{relativeTime}</span>
								</div>
							{:else}
								<div class="avatar-row">
									<span class="no-participants">No players yet</span>
									<span class="relative-time">{relativeTime}</span>
								</div>
							{/if}
							<div class="active-card-meta">
								<span>{race.participant_count} player{race.participant_count !== 1 ? 's' : ''}{#if race.pool_name} &middot; {formatPoolName(race.pool_name)}{/if}</span>
								<span class="race-organizer">
									by
									{#if race.organizer.twitch_avatar_url}
										<img src={race.organizer.twitch_avatar_url} alt="" class="organizer-avatar" />
									{/if}
									<button class="organizer-link" onclick={(e) => { e.preventDefault(); e.stopPropagation(); goto(`/user/${race.organizer.twitch_username}`); }}>
										{race.organizer.twitch_display_name || race.organizer.twitch_username}
									</button>
								</span>
							</div>
							{#if (race.status === 'running' || race.status === 'finished') && race.my_current_layer != null && race.seed_total_layers}
								<div class="progress-bar">
									<div
										class="progress-fill"
										style="width: {(race.my_current_layer / race.seed_total_layers) * 100}%"
									></div>
								</div>
							{/if}
						</a>
					{/each}
					{#each activeTraining as session}
						<a href="/training/{session.id}" class="active-card border-training">
							<div class="active-card-header">
								<span class="active-name">{session.pool_display_name || formatPoolName(session.pool_name)}</span>
								<div class="active-badges">
									<span class="badge badge-training-ghost">Solo</span>
								</div>
							</div>
							<div class="training-stats">
								<span class="training-stat">
									<span class="training-stat-label">IGT</span>
									<span class="training-stat-value">{formatIgt(session.igt_ms)}</span>
								</span>
								<span class="training-stat">
									<span class="training-stat-label">Deaths</span>
									<span class="training-stat-value">{session.death_count}</span>
								</span>
							</div>
							{#if session.current_layer != null && session.seed_total_layers}
								<div class="progress-bar">
									<div
										class="progress-fill progress-fill-training"
										style="width: {(session.current_layer / session.seed_total_layers) * 100}%"
									></div>
								</div>
							{/if}
						</a>
					{/each}
				</div>
			</section>
		{/if}

		<!-- Races to Join Section -->
		{#if joinableRaces.length > 0}
			<section class="joinable-section">
				<h2>Races to Join</h2>
				<div class="joinable-cards">
					{#each joinableRaces as race}
						<RaceCard {race} />
					{/each}
				</div>
				<div class="joinable-footer">
					<a href="/races" class="joinable-more">Browse all races</a>
				</div>
			</section>
		{/if}

		<!-- Pool Stats Section -->
		{#if poolStats && poolStats.pools.length > 0}
			<section class="pool-stats-section">
				<h2>Pool Stats</h2>
				<PoolStatsTable pools={poolStats.pools} />
			</section>
		{/if}

		<!-- Recent Activity Section -->
		{#if activity.length > 0}
			<section class="activity-section">
				<h2>Recent Activity</h2>
				<div class="activity-list">
					{#each activity as item}
						<a href={activityLink(item)} class="activity-row">
							<span class="activity-badge badge-{item.type === 'training' ? 'training' : item.status}">{activityBadge(item)}</span>
							<div class="activity-content">
								<span class="activity-name">{activityLabel(item)}</span>
								<span class="activity-details">
									{#if item.type === 'race_participant'}
										{#if item.status === 'finished' && item.placement}
											{placementMedal(item.placement)}/{item.total_participants}
											&middot;
										{:else if item.status === 'finished'}
											DNF &middot;
										{:else if item.status !== 'setup'}
											{item.total_participants} players &middot;
										{/if}
										{#if item.igt_ms > 0}
											{formatIgt(item.igt_ms)} &middot; {item.death_count} deaths
										{/if}
									{:else if item.type === 'race_organizer'}
										{item.participant_count} player{item.participant_count !== 1 ? 's' : ''}
									{:else if item.type === 'training'}
										{#if item.igt_ms > 0}
											{formatIgt(item.igt_ms)} &middot; {item.death_count} deaths
										{/if}
									{/if}
								</span>
							</div>
							<span class="activity-time">{timeAgo(item.date)}</span>
						</a>
					{/each}
				</div>
				<div class="activity-footer">
					<a href="/user/{auth.user?.twitch_username}" class="activity-more"
						>See all activity</a
					>
				</div>
			</section>
		{/if}
	{/if}
</main>

<style>
	.dashboard {
		width: 100%;
		max-width: 1200px;
		margin: 0 auto;
		padding: 2rem;
		box-sizing: border-box;
	}

	/* Loading / Error */
	.loading-state,
	.error-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		padding: 3rem 2rem;
		color: var(--color-text-secondary);
	}

	/* Settings banner */
	.settings-banner {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 0.875rem 1.25rem;
		margin-bottom: 1.5rem;
		background: rgba(59, 130, 246, 0.1);
		border: 1px solid rgba(59, 130, 246, 0.25);
		border-radius: var(--radius-lg);
	}

	.settings-banner-content {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
		flex: 1;
	}

	.settings-banner-icon {
		font-size: 1.1rem;
		flex-shrink: 0;
	}

	.settings-banner-content p {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		line-height: 1.5;
	}

	.settings-banner-content a {
		color: var(--color-info);
		font-weight: 600;
		text-decoration: none;
	}

	.settings-banner-content a:hover {
		text-decoration: underline;
	}

	.settings-banner-close {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 1.25rem;
		cursor: pointer;
		padding: 0;
		line-height: 1;
		flex-shrink: 0;
	}

	.settings-banner-close:hover {
		color: var(--color-text);
	}

	/* Welcome card */
	.welcome-section {
		margin-bottom: 2rem;
	}

	.welcome-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 2rem;
	}

	.welcome-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		margin-bottom: 1.5rem;
	}

	.welcome-title {
		margin: 0 0 0.25rem;
		color: var(--color-text);
		font-size: var(--font-size-xl);
		font-weight: 600;
	}

	.welcome-subtitle {
		margin: 0;
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
	}

	.welcome-dismiss {
		background: none;
		border: none;
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
		cursor: pointer;
		padding: 0;
		flex-shrink: 0;
	}

	.welcome-dismiss:hover {
		color: var(--color-text-secondary);
	}

	.welcome-steps {
		display: flex;
		gap: 1.5rem;
		margin-bottom: 1.75rem;
	}

	.welcome-step {
		flex: 1;
		display: flex;
		flex-direction: column;
		align-items: center;
		text-align: center;
		gap: 0.5rem;
	}

	.welcome-step-icon {
		width: 40px;
		height: 40px;
		border-radius: 50%;
		background: rgba(196, 166, 111, 0.15);
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-gold);
	}

	.welcome-step-label {
		font-size: var(--font-size-sm);
		font-weight: 600;
		color: var(--color-gold);
	}

	.welcome-step-desc {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
	}

	.welcome-actions {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.welcome-link {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		text-decoration: none;
	}

	.welcome-link:hover {
		color: var(--color-gold);
	}

	/* Stats */
	.stats-section {
		margin-bottom: 2rem;
	}

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 1rem;
	}

	.stat-card {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.25rem;
		padding: 1.25rem 1rem;
		background: var(--color-surface);
		border-radius: var(--radius-lg);
	}

	.stat-value {
		font-size: var(--font-size-2xl);
		font-weight: 700;
		color: var(--color-gold);
	}

	.stat-label {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.pool-stats-section {
		margin-bottom: 2rem;
	}

	/* Sections */
	h2 {
		margin: 0 0 1rem;
		color: var(--color-gold);
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	/* Active Now */
	.active-section {
		margin-bottom: 2rem;
	}

	.active-cards {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 0.75rem;
	}

	.active-card {
		display: flex;
		flex-direction: column;
		padding: 1rem 1.25rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		text-decoration: none;
		color: inherit;
		transition:
			border-color var(--transition),
			box-shadow var(--transition);
	}

	.active-card:hover {
		border-color: var(--color-purple);
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
	}

	.border-setup {
		border-left: 3px solid var(--color-info);
	}

	.border-running {
		border-left: 3px solid var(--color-danger);
	}

	.border-training {
		border-left: 3px solid var(--color-purple);
	}

	.active-card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}

	.active-title {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-width: 0;
	}

	.active-name {
		font-size: 1.05rem;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.active-badges {
		display: flex;
		gap: 0.4rem;
		flex-shrink: 0;
	}

	.badge-role {
		background: rgba(107, 114, 128, 0.2);
		color: var(--color-text-secondary);
	}

	.badge-training-ghost {
		background: rgba(139, 92, 246, 0.15);
		color: var(--color-purple);
	}

	/* Avatar row */
	.avatar-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.5rem;
	}

	.avatar-stack {
		display: flex;
		align-items: center;
	}

	.avatar {
		width: 26px;
		height: 26px;
		border-radius: 50%;
		border: 2px solid var(--color-surface);
		margin-left: -6px;
		object-fit: cover;
	}

	.avatar:first-child {
		margin-left: 0;
	}

	.avatar-placeholder,
	.avatar-overflow {
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--color-surface-elevated);
		color: var(--color-text-secondary);
		font-size: var(--font-size-xs);
		font-weight: 600;
	}

	.no-participants {
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.relative-time {
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
	}

	.active-card-meta {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		margin-bottom: 0.5rem;
	}

	.race-organizer {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}

	.organizer-avatar {
		width: 18px;
		height: 18px;
		border-radius: 50%;
	}

	.organizer-link {
		background: none;
		border: none;
		padding: 0;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.organizer-link:hover {
		color: var(--color-purple);
		text-decoration: underline;
	}

	/* Training stats */
	.training-stats {
		display: flex;
		gap: 1.5rem;
		margin-bottom: 0.5rem;
	}

	.training-stat {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}

	.training-stat-label {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 500;
	}

	.training-stat-value {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.progress-bar {
		height: 4px;
		background: var(--color-border);
		border-radius: 2px;
		overflow: hidden;
		margin-top: auto;
	}

	.progress-fill {
		height: 100%;
		background: var(--color-gold);
		border-radius: 2px;
		transition: width 0.3s ease;
	}

	.progress-fill-training {
		background: var(--color-purple);
	}

	/* Races to Join */
	.joinable-section {
		margin-bottom: 2rem;
	}

	.joinable-cards {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 0.75rem;
	}

	.joinable-footer {
		padding-top: 0.75rem;
		text-align: center;
	}

	.joinable-more {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-decoration: none;
	}

	.joinable-more:hover {
		color: var(--color-gold);
	}

	/* Recent Activity */
	.activity-section {
		margin-bottom: 2rem;
	}

	.activity-list {
		display: flex;
		flex-direction: column;
	}

	.activity-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 0;
		border-bottom: 1px solid var(--color-border);
		text-decoration: none;
		color: inherit;
		transition: background var(--transition);
	}

	.activity-row:hover {
		background: var(--color-surface);
	}

	.activity-row:last-child {
		border-bottom: none;
	}

	.activity-badge {
		font-size: var(--font-size-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 0.15em 0.5em;
		border-radius: var(--radius-sm);
		flex-shrink: 0;
	}

	.badge-training {
		background: rgba(139, 92, 246, 0.15);
		color: var(--color-purple);
	}

	.activity-content {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		min-width: 0;
	}

	.activity-name {
		color: var(--color-text);
		font-size: var(--font-size-sm);
	}

	.activity-details {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	.activity-time {
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
		flex-shrink: 0;
	}

	.activity-footer {
		padding-top: 0.75rem;
		text-align: center;
	}

	.activity-more {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-decoration: none;
	}

	.activity-more:hover {
		color: var(--color-gold);
	}

	/* Responsive */
	@media (max-width: 640px) {
		.dashboard {
			padding: 1rem;
		}

		.welcome-card {
			padding: 1.25rem;
		}

		.welcome-steps {
			flex-direction: column;
			gap: 1rem;
		}

		.welcome-step {
			flex-direction: row;
			text-align: left;
			gap: 0.75rem;
		}

		.welcome-step-icon {
			flex-shrink: 0;
		}

		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.active-cards {
			grid-template-columns: 1fr;
		}

		.active-card {
			padding: 0.75rem 1rem;
		}

		.joinable-cards {
			grid-template-columns: 1fr;
		}
	}
</style>
