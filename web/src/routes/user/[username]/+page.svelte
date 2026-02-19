<script lang="ts">
	import { page } from '$app/state';
	import {
		fetchUserProfile,
		fetchUserActivity,
		type UserProfile,
		type ActivityTimeline,
	} from '$lib/api';
	import { statusLabel } from '$lib/format';
	import { displayPoolName } from '$lib/utils/training';

	let username = $derived(page.params.username!);
	let profile = $state<UserProfile | null>(null);
	let activity = $state<ActivityTimeline | null>(null);
	let loading = $state(true);
	let loadingMore = $state(false);
	let error = $state<string | null>(null);

	$effect(() => {
		loadProfile();
	});

	async function loadProfile() {
		loading = true;
		error = null;
		try {
			const [p, a] = await Promise.all([
				fetchUserProfile(username),
				fetchUserActivity(username),
			]);
			profile = p;
			activity = a;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load profile.';
		} finally {
			loading = false;
		}
	}

	async function loadMore() {
		if (!activity || !activity.has_more) return;
		loadingMore = true;
		try {
			const more = await fetchUserActivity(username, activity.items.length);
			activity = {
				items: [...activity.items, ...more.items],
				total: more.total,
				has_more: more.has_more,
			};
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load more activity.';
		} finally {
			loadingMore = false;
		}
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('en-US', {
			month: 'short',
			year: 'numeric',
		});
	}

	function formatFullDate(dateStr: string): string {
		return new Date(dateStr).toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			year: 'numeric',
		});
	}

	function formatIgt(ms: number): string {
		const totalSec = Math.floor(ms / 1000);
		const h = Math.floor(totalSec / 3600);
		const m = Math.floor((totalSec % 3600) / 60);
		const s = totalSec % 60;
		if (h > 0) return `${h}:${String(m).padStart(2, '0')}:${String(s).padStart(2, '0')}`;
		return `${m}:${String(s).padStart(2, '0')}`;
	}

	function placementLabel(p: number): string {
		if (p === 1) return '1st';
		if (p === 2) return '2nd';
		if (p === 3) return '3rd';
		return `${p}th`;
	}

	function placementClass(p: number | null): string {
		if (p === 1) return 'gold';
		if (p === 2) return 'silver';
		if (p === 3) return 'bronze';
		return '';
	}

</script>

<svelte:head>
	<title>
		{profile
			? (profile.twitch_display_name || profile.twitch_username)
			: 'Profile'} - SpeedFog Racing
	</title>
</svelte:head>

<main class="profile-page">
	{#if loading}
		<p class="loading">Loading profile...</p>
	{:else if error && !profile}
		<div class="error-state">
			<p>{error}</p>
			<a href="/" class="btn btn-secondary">Home</a>
		</div>
	{:else if profile}
		<div class="profile-header">
			{#if profile.twitch_avatar_url}
				<img src={profile.twitch_avatar_url} alt="" class="profile-avatar" />
			{:else}
				<div class="profile-avatar-placeholder"></div>
			{/if}
			<div class="profile-info">
				<div class="profile-name-row">
					<h1>{profile.twitch_display_name || profile.twitch_username}</h1>
					{#if profile.role !== 'user'}
						<span class="role-badge {profile.role}">{profile.role}</span>
					{/if}
				</div>
				<p class="profile-joined">Joined {formatDate(profile.created_at)}</p>
			</div>
		</div>

		<div class="stats-grid">
			<div class="stat-card">
				<span class="stat-number">{profile.stats.race_count}</span>
				<span class="stat-label">Races</span>
			</div>
			<div class="stat-card">
				<span class="stat-number">{profile.stats.training_count}</span>
				<span class="stat-label">Trainings</span>
			</div>
			<div class="stat-card">
				<span class="stat-number">{profile.stats.podium_count}</span>
				<span class="stat-label">Podiums</span>
			</div>
			<div class="stat-card">
				<span class="stat-number">{profile.stats.first_place_count}</span>
				<span class="stat-label">1st Places</span>
			</div>
			<div class="stat-card">
				<span class="stat-number">{profile.stats.organized_count}</span>
				<span class="stat-label">Organized</span>
			</div>
			<div class="stat-card">
				<span class="stat-number">{profile.stats.casted_count}</span>
				<span class="stat-label">Casted</span>
			</div>
		</div>

		{#if activity}
			<section class="activity-section">
				<h2>Activity</h2>
				{#if activity.items.length === 0}
					<p class="empty">No activity yet.</p>
				{:else}
					<div class="timeline">
						{#each activity.items as item (item.type + '-' + ('race_id' in item ? item.race_id : 'session_id' in item ? item.session_id : '') + '-' + item.date)}
							<div class="activity-card">
								<span class="activity-date">{formatFullDate(item.date)}</span>
								{#if item.type === 'race_participant'}
									<div class="activity-body">
										<div class="badge-row">
											<span class="activity-badge participant">Race</span>
											<span class="badge badge-{item.status}">{statusLabel(item.status)}</span>
										</div>
										<a href="/race/{item.race_id}" class="activity-title">
											{item.race_name}
										</a>
										<div class="activity-details">
											{#if item.placement}
												<span class="placement {placementClass(item.placement)}">
													{placementLabel(item.placement)} / {item.total_participants}
												</span>
											{/if}
											<span class="mono">{formatIgt(item.igt_ms)}</span>
											<span>{item.death_count} deaths</span>
										</div>
									</div>
								{:else if item.type === 'race_organizer'}
									<div class="activity-body">
										<div class="badge-row">
											<span class="activity-badge organizer">Organized</span>
											<span class="badge badge-{item.status}">{statusLabel(item.status)}</span>
										</div>
										<a href="/race/{item.race_id}" class="activity-title">
											{item.race_name}
										</a>
										<div class="activity-details">
											<span>{item.participant_count} players</span>
										</div>
									</div>
								{:else if item.type === 'race_caster'}
									<div class="activity-body">
										<div class="badge-row">
											<span class="activity-badge caster">Casted</span>
											<span class="badge badge-{item.status}">{statusLabel(item.status)}</span>
										</div>
										<a href="/race/{item.race_id}" class="activity-title">
											{item.race_name}
										</a>
									</div>
								{:else if item.type === 'training'}
									<div class="activity-body">
										<div class="badge-row">
											<span class="activity-badge training">Training</span>
											<span class="badge badge-{item.status}">{statusLabel(item.status)}</span>
										</div>
										<a href="/training/{item.session_id}" class="activity-title">
											{displayPoolName(item.pool_name)}
										</a>
										<div class="activity-details">
											<span class="mono">{formatIgt(item.igt_ms)}</span>
											<span>{item.death_count} deaths</span>
										</div>
									</div>
								{/if}
							</div>
						{/each}
					</div>

					{#if activity.has_more}
						<button
							class="btn btn-secondary load-more"
							disabled={loadingMore}
							onclick={loadMore}
						>
							{loadingMore ? 'Loading...' : 'Load more'}
						</button>
					{/if}
				{/if}
			</section>
		{/if}
	{/if}
</main>

<style>
	.profile-page {
		width: 100%;
		max-width: 800px;
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

	.profile-header {
		display: flex;
		align-items: center;
		gap: 1.25rem;
		margin-bottom: 2rem;
	}

	.profile-avatar {
		width: 72px;
		height: 72px;
		border-radius: 50%;
		object-fit: cover;
		border: 2px solid var(--color-border);
	}

	.profile-avatar-placeholder {
		width: 72px;
		height: 72px;
		border-radius: 50%;
		background: var(--color-surface);
		border: 2px solid var(--color-border);
	}

	.profile-info {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.profile-name-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.profile-name-row h1 {
		margin: 0;
		font-size: var(--font-size-2xl);
		font-weight: 700;
		color: var(--color-gold);
	}

	.role-badge {
		font-size: var(--font-size-xs);
		padding: 0.15rem 0.5rem;
		border-radius: var(--radius-sm);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.role-badge.organizer {
		background: rgba(168, 85, 247, 0.15);
		color: var(--color-purple);
	}

	.role-badge.admin {
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-danger);
	}

	.profile-joined {
		margin: 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.stats-grid {
		display: grid;
		grid-template-columns: repeat(3, 1fr);
		gap: 0.75rem;
		margin-bottom: 2.5rem;
	}

	.stat-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		padding: 0.75rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.15rem;
	}

	.stat-number {
		font-size: var(--font-size-xl);
		font-weight: 700;
		font-variant-numeric: tabular-nums;
	}

	.stat-label {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.activity-section h2 {
		font-size: var(--font-size-lg);
		font-weight: 600;
		margin: 0 0 1rem 0;
		color: var(--color-text-primary);
	}

	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.timeline {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.activity-card {
		display: flex;
		align-items: flex-start;
		gap: 1rem;
		padding: 0.75rem 1rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}

	.activity-date {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		white-space: nowrap;
		min-width: 6rem;
		padding-top: 0.15rem;
	}

	.activity-body {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		flex: 1;
	}

	.activity-badge {
		font-size: 0.65rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 0.1rem 0.4rem;
		border-radius: var(--radius-sm);
		width: fit-content;
	}

	.activity-badge.participant {
		background: rgba(200, 164, 78, 0.15);
		color: var(--color-gold);
	}

	.activity-badge.organizer {
		background: rgba(200, 164, 78, 0.15);
		color: var(--color-gold);
	}

	.activity-badge.caster {
		background: rgba(200, 164, 78, 0.15);
		color: var(--color-gold);
	}

	.activity-badge.training {
		background: rgba(139, 92, 246, 0.15);
		color: var(--color-purple);
	}

	.badge-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
	}

	.activity-title {
		color: var(--color-text-primary);
		text-decoration: none;
		font-weight: 600;
	}

	.activity-title:hover {
		color: var(--color-purple);
		text-decoration: underline;
	}

	.activity-details {
		display: flex;
		gap: 0.75rem;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.placement {
		font-weight: 600;
	}

	.placement.gold {
		color: var(--color-gold);
	}

	.placement.silver {
		color: #c0c0c0;
	}

	.placement.bronze {
		color: #cd7f32;
	}

	.mono {
		font-variant-numeric: tabular-nums;
	}

	.load-more {
		margin-top: 1rem;
		width: 100%;
	}

	@media (max-width: 640px) {
		.profile-page {
			padding: 1rem;
		}

		.stats-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.activity-card {
			flex-direction: column;
			gap: 0.25rem;
		}

		.activity-date {
			min-width: auto;
		}
	}
</style>
