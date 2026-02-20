<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import {
		fetchUserProfile,
		fetchUserActivity,
		fetchMyRaces,
		fetchTrainingSessions,
		type UserProfile,
		type ActivityItem,
		type Race,
		type TrainingSession,
	} from '$lib/api';
	import { timeAgo, formatScheduledTime } from '$lib/utils/time';
	import { displayPoolName, formatIgt } from '$lib/utils/training';
	import { formatPoolName } from '$lib/utils/format';
	import { statusLabel } from '$lib/format';
	import LiveIndicator from '$lib/components/LiveIndicator.svelte';

	let profile: UserProfile | null = $state(null);
	let activity: ActivityItem[] = $state([]);
	let myRaces: Race[] = $state([]);
	let trainingSessions: TrainingSession[] = $state([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let fetched = $state(false);

	let activeRaces = $derived(myRaces.filter((r) => r.status !== 'finished'));
	let activeTraining = $derived(trainingSessions.filter((s) => s.status === 'active'));

	let activeRaceIds = $derived(new Set(activeRaces.map((r) => r.id)));
	let activeTrainingIds = $derived(new Set(activeTraining.map((s) => s.id)));
	let filteredActivity = $derived(
		activity.filter((item) => {
			if (item.type === 'training') return !activeTrainingIds.has(item.session_id);
			if ('race_id' in item) return !activeRaceIds.has(item.race_id);
			return true;
		}),
	);

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
			fetchUserActivity(username, 0, 5),
			fetchMyRaces(),
			fetchTrainingSessions(),
		])
			.then(([p, a, r, t]) => {
				profile = p;
				activity = a.items;
				myRaces = r;
				trainingSessions = t;
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
		if (item.type === 'training') return `Training (${displayPoolName(item.pool_name)})`;
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
		if (item.type === 'training') return 'Training';
		return '';
	}

	function placementMedal(placement: number): string {
		if (placement === 1) return '1st';
		if (placement === 2) return '2nd';
		if (placement === 3) return '3rd';
		return `${placement}th`;
	}

	function podiumRateDisplay(rate: number): string {
		return `${Math.round(rate * 100)}%`;
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
						<span class="stat-label">Training</span>
					</div>
					<div class="stat-card">
						<span class="stat-value">{profile.stats.podium_count}</span>
						<span class="stat-label">Podiums</span>
					</div>
				</div>
				<div class="stats-context">
					{#if profile.stats.best_recent_placement}
						<div class="stat-context-card">
							<span class="context-medal"
								>{placementMedal(profile.stats.best_recent_placement.placement)}</span
							>
							<div class="context-details">
								<span class="context-label">Best Placement</span>
								<a
									href="/race/{profile.stats.best_recent_placement.race_id}"
									class="context-link"
								>
									{profile.stats.best_recent_placement.race_name}
								</a>
								{#if profile.stats.best_recent_placement.finished_at}
									<span class="context-time"
										>{timeAgo(profile.stats.best_recent_placement.finished_at)}</span
									>
								{/if}
							</div>
						</div>
					{:else}
						<div class="stat-context-card stat-context-empty">
							<span class="context-label">No race results yet</span>
						</div>
					{/if}
					{#if profile.stats.podium_rate !== null}
						<div class="stat-context-card">
							<span class="context-rate">{podiumRateDisplay(profile.stats.podium_rate)}</span
							>
							<div class="context-details">
								<span class="context-label">Podium Rate</span>
							</div>
						</div>
					{:else}
						<div class="stat-context-card stat-context-empty">
							<span class="context-label">No podium data</span>
						</div>
					{/if}
				</div>
			</section>
		{/if}

		<!-- Active Now Section -->
		<section class="active-section">
			<h2>Active Now</h2>
			{#if activeRaces.length === 0 && activeTraining.length === 0}
				<div class="empty-state">
					<p>No active sessions</p>
					<div class="empty-actions">
						<a href="/training" class="btn btn-secondary">Start Training</a>
						<a href="/races" class="btn btn-secondary">Browse Races</a>
					</div>
				</div>
			{:else}
				<div class="active-cards">
					{#each activeRaces as race}
						{@const overflowCount = Math.max(0, race.participant_count - race.participant_previews.length)}
						{@const relativeTime = race.scheduled_at && race.status === 'setup' ? formatScheduledTime(race.scheduled_at) : timeAgo(race.created_at)}
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
								<span class="active-name">{displayPoolName(session.pool_name)}</span>
								<div class="active-badges">
									<span class="badge badge-training-ghost">Training</span>
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
		{#if filteredActivity.length > 0}
			<section class="activity-section">
				<h2>Recent Activity</h2>
				<div class="activity-list">
					{#each filteredActivity as item}
						<a href={activityLink(item)} class="activity-row">
							<span class="activity-badge badge-{item.type}">{activityBadge(item)}</span>
							<span class="activity-name">{activityLabel(item)}</span>
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

	/* Stats */
	.stats-section {
		margin-bottom: 2rem;
	}

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 1rem;
		margin-bottom: 1rem;
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

	.stats-context {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 1rem;
	}

	.stat-context-card {
		display: flex;
		align-items: center;
		gap: 1rem;
		padding: 1rem 1.25rem;
		background: var(--color-surface);
		border-radius: var(--radius-lg);
	}

	.stat-context-empty {
		justify-content: center;
		color: var(--color-text-disabled);
	}

	.context-medal {
		font-size: var(--font-size-xl);
		font-weight: 700;
		color: var(--color-gold);
		min-width: 3rem;
		text-align: center;
	}

	.context-rate {
		font-size: var(--font-size-xl);
		font-weight: 700;
		color: var(--color-gold);
		min-width: 3rem;
		text-align: center;
	}

	.context-details {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.context-label {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.context-link {
		color: var(--color-text);
		text-decoration: none;
		font-size: var(--font-size-sm);
	}

	.context-link:hover {
		color: var(--color-gold);
	}

	.context-time {
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
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

	.badge-race_participant {
		background: var(--color-gold);
		color: var(--color-bg);
	}

	.badge-race_organizer {
		background: var(--color-gold);
		color: var(--color-bg);
	}

	.badge-race_caster {
		background: var(--color-gold);
		color: var(--color-bg);
	}

	.badge-training {
		background: var(--color-purple);
		color: white;
	}

	.activity-name {
		flex: 1;
		color: var(--color-text);
		font-size: var(--font-size-sm);
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

		.stats-context {
			grid-template-columns: 1fr;
		}

		.active-cards {
			grid-template-columns: 1fr;
		}

		.active-card {
			padding: 0.75rem 1rem;
		}
	}
</style>
