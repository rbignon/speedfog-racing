<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import {
		fetchAdminUsers,
		updateAdminUserRole,
		fetchAdminSeedStats,
		adminDiscardPool,
		adminScanPool,
		fetchAdminActivity,
		type AdminUser,
		type AdminPoolStats,
		type ActivityTimeline,
		type ActivityItem
	} from '$lib/api';
	import { statusLabel } from '$lib/format';
	import { displayPoolName } from '$lib/utils/training';

	type Tab = 'users' | 'seeds' | 'activity';
	let activeTab: Tab = $state('users');

	let users: AdminUser[] = $state([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let authChecked = $state(false);

	let seedStats: AdminPoolStats | null = $state(null);
	let seedsLoading = $state(false);
	let actionLoading = $state<Record<string, boolean>>({});

	let activity: ActivityTimeline | null = $state(null);
	let activityLoading = $state(false);
	let activityLoadingMore = $state(false);

	$effect(() => {
		if (auth.initialized && !authChecked) {
			authChecked = true;
			if (!auth.isAdmin) {
				goto('/');
				return;
			}
			loadUsers();
		}
	});

	async function loadUsers() {
		try {
			users = await fetchAdminUsers();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load users.';
		} finally {
			loading = false;
		}
	}

	async function loadSeedStats() {
		seedsLoading = true;
		try {
			seedStats = await fetchAdminSeedStats();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load seed stats.';
		} finally {
			seedsLoading = false;
		}
	}

	async function loadActivity() {
		activityLoading = true;
		try {
			activity = await fetchAdminActivity();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load activity.';
		} finally {
			activityLoading = false;
		}
	}

	async function loadMoreActivity() {
		if (!activity || !activity.has_more) return;
		activityLoadingMore = true;
		try {
			const more = await fetchAdminActivity(activity.items.length);
			activity = {
				items: [...activity.items, ...more.items],
				total: more.total,
				has_more: more.has_more,
			};
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load more activity.';
		} finally {
			activityLoadingMore = false;
		}
	}

	function switchTab(tab: Tab) {
		activeTab = tab;
		if (tab === 'seeds' && !seedStats) {
			loadSeedStats();
		}
		if (tab === 'activity' && !activity) {
			loadActivity();
		}
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

	async function changeRole(user: AdminUser, newRole: string) {
		try {
			const updated = await updateAdminUserRole(user.id, newRole);
			const idx = users.findIndex((u) => u.id === updated.id);
			if (idx !== -1) {
				users[idx] = updated;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to update role.';
		}
	}

	async function handleDiscard(poolName: string) {
		if (!confirm(`Discard all available seeds in "${poolName}"? This cannot be undone.`)) return;
		actionLoading = { ...actionLoading, [`discard_${poolName}`]: true };
		try {
			const result = await adminDiscardPool(poolName);
			error = null;
			await loadSeedStats();
			if (result.discarded === 0) {
				error = `No available seeds to discard in "${poolName}".`;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to discard seeds.';
		} finally {
			actionLoading = { ...actionLoading, [`discard_${poolName}`]: false };
		}
	}

	async function handleScan(poolName: string) {
		actionLoading = { ...actionLoading, [`scan_${poolName}`]: true };
		try {
			await adminScanPool(poolName);
			error = null;
			await loadSeedStats();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to scan pool.';
		} finally {
			actionLoading = { ...actionLoading, [`scan_${poolName}`]: false };
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return 'Never';
		const d = new Date(iso);
		const pad = (n: number) => String(n).padStart(2, '0');
		return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
	}
</script>

<svelte:head>
	<title>Admin - SpeedFog Racing</title>
</svelte:head>

<main>
	<h1>Admin</h1>

	<div class="tabs">
		<button class="tab" class:active={activeTab === 'users'} onclick={() => switchTab('users')}>
			Users
		</button>
		<button class="tab" class:active={activeTab === 'seeds'} onclick={() => switchTab('seeds')}>
			Seeds
		</button>
		<button class="tab" class:active={activeTab === 'activity'} onclick={() => switchTab('activity')}>
			Activity
		</button>
	</div>

	{#if error}
		<div class="error">
			{error}
			<button onclick={() => (error = null)}>&times;</button>
		</div>
	{/if}

	{#if activeTab === 'users'}
		{#if loading}
			<p class="loading">Loading users...</p>
		{:else if users.length === 0}
			<p class="empty">No users found.</p>
		{:else}
			<div class="table-wrapper">
				<table>
					<thead>
						<tr>
							<th>User</th>
							<th>Role</th>
							<th class="num-col">Trainings</th>
							<th class="num-col">Races</th>
							<th>Last Seen</th>
							<th>Joined</th>
						</tr>
					</thead>
					<tbody>
						{#each users as user (user.id)}
							<tr>
								<td class="user-cell">
									{#if user.twitch_avatar_url}
										<img src={user.twitch_avatar_url} alt="" class="avatar" />
									{/if}
									<a href="/user/{user.twitch_username}" class="username-link">
										{user.twitch_display_name || user.twitch_username}
									</a>
								</td>
								<td>
									{#if user.role === 'admin'}
										<span class="role-badge admin">admin</span>
									{:else}
										<select
											value={user.role}
											onchange={(e) => changeRole(user, e.currentTarget.value)}
										>
											<option value="user">user</option>
											<option value="organizer">organizer</option>
										</select>
									{/if}
								</td>
								<td class="num-cell">{user.training_count}</td>
								<td class="num-cell">{user.race_count}</td>
								<td class="date-cell">{formatDate(user.last_seen)}</td>
								<td class="date-cell">{formatDate(user.created_at)}</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{:else if activeTab === 'seeds'}
		{#if seedsLoading}
			<p class="loading">Loading seed stats...</p>
		{:else if !seedStats || Object.keys(seedStats.pools).length === 0}
			<p class="empty">No seed pools found.</p>
		{:else}
			<div class="table-wrapper">
				<table>
					<thead>
						<tr>
							<th>Pool Name</th>
							<th class="num-col">Available</th>
							<th class="num-col">Consumed</th>
							<th class="num-col">Discarded</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each Object.entries(seedStats.pools) as [poolName, stats] (poolName)}
							<tr>
								<td class="pool-name">{poolName}</td>
								<td class="num-cell">{stats.available}</td>
								<td class="num-cell">{stats.consumed}</td>
								<td class="num-cell">{stats.discarded}</td>
								<td class="actions-cell">
									<button
										class="action-btn scan"
										disabled={actionLoading[`scan_${poolName}`]}
										onclick={() => handleScan(poolName)}
									>
										{actionLoading[`scan_${poolName}`] ? 'Scanning...' : 'Scan'}
									</button>
									<button
										class="action-btn discard"
										disabled={actionLoading[`discard_${poolName}`] || stats.available === 0}
										onclick={() => handleDiscard(poolName)}
									>
										{actionLoading[`discard_${poolName}`] ? 'Discarding...' : 'Discard'}
									</button>
								</td>
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/if}
	{:else if activeTab === 'activity'}
		{#if activityLoading}
			<p class="loading">Loading activity...</p>
		{:else if !activity || activity.items.length === 0}
			<p class="empty">No activity yet.</p>
		{:else}
			<div class="timeline">
				{#each activity.items as item (item.type + '-' + ('race_id' in item ? item.race_id : 'session_id' in item ? item.session_id : '') + '-' + item.date + '-' + (item.user?.id ?? ''))}
					<div class="activity-card">
						{#if item.user}
							<a href="/user/{item.user.twitch_username}" class="activity-user">
								{#if item.user.twitch_avatar_url}
									<img src={item.user.twitch_avatar_url} alt="" class="activity-avatar" />
								{/if}
								<span class="activity-username">{item.user.twitch_display_name || item.user.twitch_username}</span>
							</a>
						{/if}
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
					disabled={activityLoadingMore}
					onclick={loadMoreActivity}
				>
					{activityLoadingMore ? 'Loading...' : 'Load more'}
				</button>
			{/if}
		{/if}
	{/if}
</main>

<style>
	main {
		max-width: 900px;
		margin: 0 auto;
		padding: 2rem;
	}

	h1 {
		color: var(--color-text);
		font-size: var(--font-size-2xl);
		font-weight: 600;
		margin-bottom: 1.5rem;
	}

	.tabs {
		display: flex;
		gap: 0;
		margin-bottom: 1.5rem;
		border-bottom: 1px solid var(--color-border);
	}

	.tab {
		padding: 0.6rem 1.25rem;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		font-weight: 500;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		cursor: pointer;
		transition:
			color 0.15s,
			border-color 0.15s;
	}

	.tab:hover {
		color: var(--color-text);
	}

	.tab.active {
		color: var(--color-purple);
		border-bottom-color: var(--color-purple);
	}

	.error {
		background: var(--color-danger-dark);
		color: white;
		padding: 0.75rem 1rem;
		border-radius: var(--radius-sm);
		margin-bottom: 1rem;
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.error button {
		background: none;
		border: none;
		color: white;
		font-size: 1.25rem;
		cursor: pointer;
	}

	.loading,
	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.table-wrapper {
		overflow-x: auto;
	}

	table {
		width: 100%;
		border-collapse: collapse;
	}

	th {
		text-align: left;
		padding: 0.75rem 1rem;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		border-bottom: 1px solid var(--color-border);
	}

	td {
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--color-border);
		vertical-align: middle;
	}

	tr:hover td {
		background: var(--color-surface);
	}

	.user-cell {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 2px solid var(--color-border);
	}

	.username-link {
		font-weight: 500;
		color: inherit;
		text-decoration: none;
	}

	.username-link:hover {
		color: var(--color-purple);
		text-decoration: underline;
	}

	.num-col {
		text-align: center;
	}

	.num-cell {
		text-align: center;
		font-variant-numeric: tabular-nums;
	}

	.date-cell {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		white-space: nowrap;
	}

	.pool-name {
		font-weight: 500;
		font-family: var(--font-family-mono, monospace);
		font-size: var(--font-size-sm);
	}

	.actions-cell {
		display: flex;
		gap: 0.5rem;
	}

	.action-btn {
		padding: 0.3rem 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		white-space: nowrap;
		transition:
			background 0.15s,
			border-color 0.15s;
	}

	.action-btn:hover:not(:disabled) {
		border-color: var(--color-text-secondary);
	}

	.action-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.action-btn.discard {
		color: var(--color-danger-dark);
		border-color: var(--color-danger-dark);
	}

	.action-btn.discard:hover:not(:disabled) {
		background: var(--color-danger-dark);
		color: white;
	}

	.role-badge {
		display: inline-block;
		padding: 0.2rem 0.6rem;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-sm);
		font-weight: 500;
	}

	.role-badge.admin {
		background: var(--color-purple);
		color: white;
	}

	select {
		padding: 0.35rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
	}

	select:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	/* Activity feed styles */
	.timeline {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.activity-card {
		display: flex;
		align-items: flex-start;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}

	.activity-user {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		text-decoration: none;
		color: inherit;
		flex-shrink: 0;
		min-width: 8rem;
	}

	.activity-user:hover .activity-username {
		color: var(--color-purple);
		text-decoration: underline;
	}

	.activity-avatar {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		border: 1px solid var(--color-border);
	}

	.activity-username {
		font-size: var(--font-size-sm);
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 7rem;
	}

	.activity-date {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		white-space: nowrap;
		min-width: 5.5rem;
		padding-top: 0.15rem;
	}

	.activity-body {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		flex: 1;
		min-width: 0;
	}

	.badge-row {
		display: flex;
		align-items: center;
		gap: 0.4rem;
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
		background: rgba(59, 130, 246, 0.15);
		color: var(--color-blue, #3b82f6);
	}

	.activity-badge.organizer {
		background: rgba(168, 85, 247, 0.15);
		color: var(--color-purple);
	}

	.activity-badge.caster {
		background: rgba(236, 72, 153, 0.15);
		color: #ec4899;
	}

	.activity-badge.training {
		background: rgba(34, 197, 94, 0.15);
		color: var(--color-success);
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

	.btn-secondary {
		padding: 0.5rem 1rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		transition: background 0.15s, border-color 0.15s;
	}

	.btn-secondary:hover:not(:disabled) {
		border-color: var(--color-text-secondary);
	}

	.btn-secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	@media (max-width: 640px) {
		main {
			padding: 1rem;
		}

		h1 {
			font-size: var(--font-size-xl);
		}

		th,
		td {
			padding: 0.5rem;
		}

		.activity-card {
			flex-direction: column;
			gap: 0.25rem;
		}

		.activity-user {
			min-width: auto;
		}

		.activity-date {
			min-width: auto;
		}
	}
</style>
