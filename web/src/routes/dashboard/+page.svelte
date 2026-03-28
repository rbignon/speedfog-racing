<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import {
		fetchUserProfile,
		fetchUserActivity,
		fetchUserPoolStats,
		fetchMyRaces,
		fetchTrainingSessions,
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

	let profile: UserProfile | null = $state(null);
	let poolStats: UserPoolStats | null = $state(null);
	let activity: ActivityItem[] = $state([]);
	let myRaces: Race[] = $state([]);
	let trainingSessions: TrainingSession[] = $state([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let fetched = $state(false);

	let activeRaces = $derived(myRaces.filter((r) => r.status !== 'finished'));
	let activeTraining = $derived(trainingSessions.filter((s) => s.status === 'active'));

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
		])
			.then(([p, a, r, t, ps]) => {
				profile = p;
				activity = a.items;
				myRaces = r;
				trainingSessions = t;
				poolStats = ps;
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

		<!-- Stats Section -->
		{#if profile}
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

		<!-- Pool Stats Section -->
		{#if poolStats && poolStats.pools.length > 0}
			<section class="pool-stats-section">
				<h2>Pool Stats</h2>
				<PoolStatsTable pools={poolStats.pools} />
			</section>
		{/if}

		<!-- Active Now Section -->
		<section class="active-section">
			<h2>Active Now</h2>
			{#if activeRaces.length === 0 && activeTraining.length === 0}
				<div class="empty-state">
					<p>No active sessions</p>
					<div class="empty-actions">
						<a href="/training" class="btn btn-secondary">Play Solo</a>
						{#if auth.canCreateRace}
							<a href="/race/new" class="btn btn-primary">Create Race</a>
						{/if}
						<a href="/races" class="btn btn-secondary">Browse Races</a>
					</div>
					<a
						href="https://discord.gg/Qmw67J3mR9"
						class="discord-link"
						target="_blank"
						rel="noopener noreferrer"
					>
						<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16"
							><path
								d="M20.317 4.37a19.791 19.791 0 0 0-4.885-1.515.074.074 0 0 0-.079.037c-.21.375-.444.864-.608 1.25a18.27 18.27 0 0 0-5.487 0 12.64 12.64 0 0 0-.617-1.25.077.077 0 0 0-.079-.037A19.736 19.736 0 0 0 3.677 4.37a.07.07 0 0 0-.032.027C.533 9.046-.32 13.58.099 18.057a.082.082 0 0 0 .031.057 19.9 19.9 0 0 0 5.993 3.03.078.078 0 0 0 .084-.028c.462-.63.874-1.295 1.226-1.994a.076.076 0 0 0-.041-.106 13.107 13.107 0 0 1-1.872-.892.077.077 0 0 1-.008-.128 10.2 10.2 0 0 0 .372-.292.074.074 0 0 1 .077-.01c3.928 1.793 8.18 1.793 12.062 0a.074.074 0 0 1 .078.01c.12.098.246.198.373.292a.077.077 0 0 1-.006.127 12.299 12.299 0 0 1-1.873.892.077.077 0 0 0-.041.107c.36.698.772 1.362 1.225 1.993a.076.076 0 0 0 .084.028 19.839 19.839 0 0 0 6.002-3.03.077.077 0 0 0 .032-.054c.5-5.177-.838-9.674-3.549-13.66a.061.061 0 0 0-.031-.03z"
							/></svg
						>
						{#if auth.canCreateRace}
							Find players on Discord
						{:else}
							Find players or request race creation rights on Discord
						{/if}
					</a>
				</div>
			{:else}
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
			{/if}
		</section>

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

	.empty-state {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
		padding: 2rem;
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		color: var(--color-text-secondary);
	}

	.empty-state p {
		margin: 0;
	}

	.empty-actions {
		display: flex;
		gap: 0.75rem;
	}

	.discord-link {
		display: inline-flex;
		align-items: center;
		gap: 0.4rem;
		color: var(--color-text-secondary);
		text-decoration: none;
		font-size: var(--font-size-sm);
		transition:
			color 0.15s ease;
	}

	.discord-link:hover {
		color: #5865f2;
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

		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.active-cards {
			grid-template-columns: 1fr;
		}

		.active-card {
			padding: 0.75rem 1rem;
		}
	}
</style>
