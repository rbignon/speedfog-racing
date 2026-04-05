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
		adminRecalculateStats,
		fetchReportedSeeds,
		resolveReportedSeed,
		fetchAdminAnalytics,
		type AdminUser,
		type AdminPoolStats,
		type ActivityTimeline,
		type ReportedSeed,
		type AdminAnalytics
	} from '$lib/api';
	import { statusLabel } from '$lib/format';
	import { formatPoolName } from '$lib/utils/format';
	import { Chart, registerables } from 'chart.js';
	Chart.register(...registerables);

	type Tab = 'users' | 'seeds' | 'stats' | 'activity';
	let activeTab: Tab = $state('users');

	let users: AdminUser[] = $state([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let authChecked = $state(false);

	type UserSortKey = 'username' | 'training_count' | 'race_count' | 'last_seen' | 'created_at';
	let userSortKey = $state<UserSortKey>('last_seen');
	let userSortAsc = $state(false);

	let sortedUsers = $derived.by(() => {
		const list = [...users];
		list.sort((a, b) => {
			let cmp = 0;
			if (userSortKey === 'username') {
				const nameA = (a.twitch_display_name || a.twitch_username).toLowerCase();
				const nameB = (b.twitch_display_name || b.twitch_username).toLowerCase();
				cmp = nameA.localeCompare(nameB);
			} else if (userSortKey === 'training_count' || userSortKey === 'race_count') {
				cmp = a[userSortKey] - b[userSortKey];
			} else {
				const va = a[userSortKey];
				const vb = b[userSortKey];
				const ta = va ? new Date(va).getTime() : 0;
				const tb = vb ? new Date(vb).getTime() : 0;
				cmp = ta - tb;
			}
			return userSortAsc ? cmp : -cmp;
		});
		return list;
	});

	function handleUserSort(key: UserSortKey) {
		if (userSortKey === key) {
			userSortAsc = !userSortAsc;
		} else {
			userSortKey = key;
			userSortAsc = key === 'username';
		}
	}

	function userSortIndicator(key: UserSortKey): string {
		if (userSortKey !== key) return '';
		return userSortAsc ? ' \u25B2' : ' \u25BC';
	}

	let seedStats: AdminPoolStats | null = $state(null);
	let seedsLoading = $state(false);
	let actionLoading = $state<Record<string, boolean>>({});

	let activity: ActivityTimeline | null = $state(null);
	let activityLoading = $state(false);
	let activityLoadingMore = $state(false);

	let recalcLoading = $state(false);
	let recalcMessage = $state<{ type: 'success' | 'error'; text: string } | null>(null);

	let reportedSeeds: ReportedSeed[] = $state([]);
	let reportedLoading = $state(false);

	let analytics: AdminAnalytics | null = $state(null);
	let analyticsLoading = $state(false);

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
				has_more: more.has_more
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
			loadReportedSeeds();
		}
		if (tab === 'stats' && !analytics) {
			loadAnalytics();
		}
		if (tab === 'activity' && !activity) {
			loadActivity();
		}
	}

	async function loadReportedSeeds() {
		reportedLoading = true;
		try {
			reportedSeeds = await fetchReportedSeeds();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load reported seeds.';
		} finally {
			reportedLoading = false;
		}
	}

	async function loadAnalytics() {
		analyticsLoading = true;
		try {
			analytics = await fetchAdminAnalytics();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load analytics.';
		} finally {
			analyticsLoading = false;
		}
	}

	async function handleResolve(seedId: string, action: 'discard' | 'restore') {
		actionLoading = { ...actionLoading, [`resolve_${seedId}`]: true };
		try {
			await resolveReportedSeed(seedId, action);
			reportedSeeds = reportedSeeds.filter((s) => s.id !== seedId);
			await loadSeedStats();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to resolve seed.';
		} finally {
			actionLoading = { ...actionLoading, [`resolve_${seedId}`]: false };
		}
	}

	function formatFullDate(dateStr: string): string {
		const d = new Date(dateStr);
		const date = d.toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			year: 'numeric'
		});
		const time = d.toLocaleTimeString('en-US', {
			hour: '2-digit',
			minute: '2-digit',
			hour12: false
		});
		return `${date} ${time}`;
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
		if (
			!confirm(
				`Discard all available seeds in "${formatPoolName(poolName)}"? This cannot be undone.`
			)
		)
			return;
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

	async function handleRecalculateStats() {
		recalcLoading = true;
		recalcMessage = null;
		try {
			await adminRecalculateStats();
			recalcMessage = { type: 'success', text: 'Stats recalculated successfully.' };
		} catch (e) {
			recalcMessage = {
				type: 'error',
				text: e instanceof Error ? e.message : 'Failed to recalculate stats.'
			};
		} finally {
			recalcLoading = false;
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return 'Never';
		const d = new Date(iso);
		const pad = (n: number) => String(n).padStart(2, '0');
		return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
	}

	let newUsersCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
	let raceSoloCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
	let soloCompletionCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
	let avgParticipantsCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
	let timezoneCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
	let charts: Chart[] = [];

	function destroyCharts() {
		charts.forEach((c) => c.destroy());
		charts = [];
	}

	function renderCharts(data: AdminAnalytics) {
		destroyCharts();
		const gridColor = 'rgba(255,255,255,0.06)';
		const tickColor = '#888';
		const defaultScales = {
			x: { grid: { display: false }, ticks: { color: tickColor, font: { size: 10 } } },
			y: {
				beginAtZero: true,
				grid: { color: gridColor },
				ticks: { color: tickColor, font: { size: 10 } }
			}
		};
		const defaultPlugins = { legend: { display: false } };

		charts.push(
			new Chart(newUsersCanvas, {
				type: 'bar',
				data: {
					labels: data.weekly.weeks,
					datasets: [
						{
							data: data.weekly.new_users,
							backgroundColor: 'rgba(139,92,246,0.6)',
							borderColor: '#8b5cf6',
							borderWidth: 1
						}
					]
				},
				options: { responsive: true, plugins: defaultPlugins, scales: defaultScales }
			})
		);

		charts.push(
			new Chart(raceSoloCanvas, {
				type: 'bar',
				data: {
					labels: data.weekly.weeks,
					datasets: [
						{
							label: 'Races',
							data: data.weekly.races,
							backgroundColor: 'rgba(200,164,78,0.6)',
							borderColor: '#c8a44e',
							borderWidth: 1
						},
						{
							label: 'Solo',
							data: data.weekly.solo,
							backgroundColor: 'rgba(139,92,246,0.6)',
							borderColor: '#8b5cf6',
							borderWidth: 1
						}
					]
				},
				options: {
					responsive: true,
					scales: {
						x: { ...defaultScales.x, stacked: true },
						y: { ...defaultScales.y, stacked: true }
					},
					plugins: {
						legend: {
							display: true,
							labels: { color: tickColor, font: { size: 10 }, boxWidth: 12 }
						}
					}
				}
			})
		);

		charts.push(
			new Chart(soloCompletionCanvas, {
				type: 'bar',
				data: {
					labels: data.weekly.weeks,
					datasets: [
						{
							label: 'Finished',
							data: data.weekly.solo_finished,
							backgroundColor: 'rgba(34,197,94,0.5)',
							borderColor: '#22c55e',
							borderWidth: 1
						},
						{
							label: 'Abandoned',
							data: data.weekly.solo_abandoned,
							backgroundColor: 'rgba(239,68,68,0.5)',
							borderColor: '#ef4444',
							borderWidth: 1
						}
					]
				},
				options: {
					responsive: true,
					scales: {
						x: { ...defaultScales.x, stacked: true },
						y: { ...defaultScales.y, stacked: true }
					},
					plugins: {
						legend: {
							display: true,
							labels: { color: tickColor, font: { size: 10 }, boxWidth: 12 }
						}
					}
				}
			})
		);

		charts.push(
			new Chart(avgParticipantsCanvas, {
				type: 'bar',
				data: {
					labels: data.weekly.weeks,
					datasets: [
						{
							data: data.weekly.avg_participants,
							backgroundColor: 'rgba(200,164,78,0.6)',
							borderColor: '#c8a44e',
							borderWidth: 1
						}
					]
				},
				options: { responsive: true, plugins: defaultPlugins, scales: defaultScales }
			})
		);

		if (data.timezones.length > 0) {
			charts.push(
				new Chart(timezoneCanvas, {
					type: 'bar',
					data: {
						labels: data.timezones.map((t) => t.timezone.replace(/_/g, ' ')),
						datasets: [
							{
								data: data.timezones.map((t) => t.count),
								backgroundColor: 'rgba(139,92,246,0.6)',
								borderColor: '#8b5cf6',
								borderWidth: 1
							}
						]
					},
					options: {
						responsive: true,
						plugins: defaultPlugins,
						scales: {
							x: {
								grid: { display: false },
								ticks: { color: tickColor, font: { size: 9 }, maxRotation: 45 }
							},
							y: {
								beginAtZero: true,
								grid: { color: gridColor },
								ticks: { color: tickColor, font: { size: 10 }, stepSize: 1 }
							}
						}
					}
				})
			);
		}
	}

	$effect(() => {
		if (analytics && newUsersCanvas) {
			renderCharts($state.snapshot(analytics));
		}
		return () => destroyCharts();
	});
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
		<button class="tab" class:active={activeTab === 'stats'} onclick={() => switchTab('stats')}>
			Stats
		</button>
		<button
			class="tab"
			class:active={activeTab === 'activity'}
			onclick={() => switchTab('activity')}
		>
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
							<th>
								<button class="sort-btn" onclick={() => handleUserSort('username')}>
									User{userSortIndicator('username')}
								</button>
							</th>
							<th>Role</th>
							<th class="num-col">
								<button class="sort-btn" onclick={() => handleUserSort('training_count')}>
									Solo{userSortIndicator('training_count')}
								</button>
							</th>
							<th class="num-col">
								<button class="sort-btn" onclick={() => handleUserSort('race_count')}>
									Races{userSortIndicator('race_count')}
								</button>
							</th>
							<th>
								<button class="sort-btn" onclick={() => handleUserSort('last_seen')}>
									Last Seen{userSortIndicator('last_seen')}
								</button>
							</th>
							<th>
								<button class="sort-btn" onclick={() => handleUserSort('created_at')}>
									Joined{userSortIndicator('created_at')}
								</button>
							</th>
						</tr>
					</thead>
					<tbody>
						{#each sortedUsers as user (user.id)}
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
		{#if seedsLoading || reportedLoading}
			<p class="loading">Loading seed stats...</p>
		{:else if !seedStats || Object.keys(seedStats.pools).length === 0}
			<p class="empty">No seed pools found.</p>
		{:else}
			<div class="reported-section">
				<h2 class="section-title">Reported Seeds</h2>
				{#if reportedSeeds.length > 0}
					<div class="table-wrapper">
						<table>
							<thead>
								<tr>
									<th>Seed</th>
									<th>Pool</th>
									<th>Reporter</th>
									<th>Reason</th>
									<th>Date</th>
									<th>Actions</th>
								</tr>
							</thead>
							<tbody>
								{#each reportedSeeds as seed (seed.id)}
									<tr>
										<td class="mono">{seed.seed_number}</td>
										<td>{formatPoolName(seed.pool_name)}</td>
										<td>{seed.reported_by}</td>
										<td class="reason-cell" title={seed.reported_reason || ''}
											>{seed.reported_reason || '-'}</td
										>
										<td class="date-cell">{formatDate(seed.reported_at)}</td>
										<td class="actions-cell">
											<button
												class="action-btn discard"
												disabled={actionLoading[`resolve_${seed.id}`]}
												onclick={() => handleResolve(seed.id, 'discard')}
											>
												Discard
											</button>
											<button
												class="action-btn scan"
												disabled={actionLoading[`resolve_${seed.id}`]}
												onclick={() => handleResolve(seed.id, 'restore')}
											>
												Restore
											</button>
										</td>
									</tr>
								{/each}
							</tbody>
						</table>
					</div>
				{:else}
					<p class="empty">No reported seeds.</p>
				{/if}
			</div>
			<h2 class="section-title">Seed Pools</h2>
			<div class="table-wrapper">
				<table>
					<thead>
						<tr>
							<th>Pool Name</th>
							<th class="num-col">Available</th>
							<th class="num-col">Consumed</th>
							<th class="num-col">Reported</th>
							<th class="num-col">Discarded</th>
							<th>Actions</th>
						</tr>
					</thead>
					<tbody>
						{#each Object.entries(seedStats.pools).sort( ([a], [b]) => a.localeCompare(b) ) as [poolName, stats] (poolName)}
							<tr>
								<td class="pool-name">{formatPoolName(poolName)}</td>
								<td class="num-cell">{stats.available}</td>
								<td class="num-cell">{stats.consumed}</td>
								<td class="num-cell">{stats.reported ?? 0}</td>
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
	{:else if activeTab === 'stats'}
		{#if analyticsLoading}
			<p class="loading">Loading analytics...</p>
		{:else if !analytics}
			<p class="empty">
				Failed to load analytics. <button class="link-btn" onclick={loadAnalytics}>Retry</button>
			</p>
		{:else}
			<div class="kpi-grid">
				<div class="kpi-card">
					<div class="kpi-label">Total Users</div>
					<div class="kpi-value">{analytics.kpis.total_users}</div>
					<div class="kpi-sub">+{analytics.kpis.new_users_this_month} this month</div>
				</div>
				<div class="kpi-card">
					<div class="kpi-label">Active (30d)</div>
					<div class="kpi-value">{analytics.kpis.active_users_30d}</div>
					<div class="kpi-sub">{analytics.kpis.active_users_pct}% of total</div>
				</div>
				<div class="kpi-card">
					<div class="kpi-label">Races (finished)</div>
					<div class="kpi-value kpi-gold">{analytics.kpis.total_races_finished}</div>
					<div class="kpi-sub">avg {analytics.kpis.avg_participants} players</div>
				</div>
				<div class="kpi-card">
					<div class="kpi-label">Solo Sessions</div>
					<div class="kpi-value kpi-purple">{analytics.kpis.total_solo}</div>
					<div class="kpi-sub">{analytics.kpis.solo_completion_pct}% finished</div>
				</div>
			</div>

			<div class="charts-grid">
				<div class="chart-box">
					<div class="chart-title">New Users per Week</div>
					<canvas bind:this={newUsersCanvas}></canvas>
				</div>
				<div class="chart-box">
					<div class="chart-title">Races & Solo per Week</div>
					<canvas bind:this={raceSoloCanvas}></canvas>
				</div>
				<div class="chart-box">
					<div class="chart-title">Solo Completion Rate</div>
					<canvas bind:this={soloCompletionCanvas}></canvas>
				</div>
				<div class="chart-box">
					<div class="chart-title">Avg Participants per Race</div>
					<canvas bind:this={avgParticipantsCanvas}></canvas>
				</div>
			</div>

			{@const raceMax = Math.max(1, ...analytics.heatmaps.race_players.flat())}
			{@const soloMax = Math.max(1, ...analytics.heatmaps.solo.flat())}
			{@const hours = [
				'00h',
				'02h',
				'04h',
				'06h',
				'08h',
				'10h',
				'12h',
				'14h',
				'16h',
				'18h',
				'20h',
				'22h'
			]}
			{@const days = ['Mo', 'Tu', 'We', 'Th', 'Fr', 'Sa', 'Su']}

			<div class="heatmaps-row">
				<div class="heatmap-box">
					<div class="heatmap-title heatmap-gold">
						Race Players <span class="heatmap-tz">(UTC)</span>
					</div>
					<div class="heatmap-grid">
						<div class="heatmap-corner"></div>
						{#each days as day}
							<div class="heatmap-day">{day}</div>
						{/each}
						{#each hours as hour, rowIdx}
							<div class="heatmap-hour">{hour}</div>
							{#each analytics.heatmaps.race_players[rowIdx] as val}
								<div
									class="heatmap-cell"
									style="background: rgba(200,164,78,{(val / raceMax) * 0.9})"
									title={String(val)}
								></div>
							{/each}
						{/each}
					</div>
					<div class="heatmap-legend">
						<span>0</span>
						<div class="heatmap-legend-bar heatmap-legend-gold"></div>
						<span>{raceMax}</span>
					</div>
				</div>

				<div class="heatmap-box">
					<div class="heatmap-title heatmap-purple">
						Solo <span class="heatmap-tz">(UTC)</span>
					</div>
					<div class="heatmap-grid">
						<div class="heatmap-corner"></div>
						{#each days as day}
							<div class="heatmap-day">{day}</div>
						{/each}
						{#each hours as hour, rowIdx}
							<div class="heatmap-hour">{hour}</div>
							{#each analytics.heatmaps.solo[rowIdx] as val}
								<div
									class="heatmap-cell"
									style="background: rgba(139,92,246,{(val / soloMax) * 0.9})"
									title={String(val)}
								></div>
							{/each}
						{/each}
					</div>
					<div class="heatmap-legend">
						<span>0</span>
						<div class="heatmap-legend-bar heatmap-legend-purple"></div>
						<span>{soloMax}</span>
					</div>
				</div>
			</div>

			{#if analytics.timezones.length > 0}
				<div class="chart-box chart-full">
					<div class="chart-title">Players by Timezone</div>
					<canvas bind:this={timezoneCanvas}></canvas>
				</div>
			{/if}

			<div class="stats-section">
				<h2 class="section-title">Recalculate</h2>
				<p class="stats-description">
					Recompute cached statistics for all users and participants from raw race data.
				</p>
				<div class="stats-actions">
					<button
						class="action-btn recalc"
						disabled={recalcLoading}
						onclick={handleRecalculateStats}
					>
						{recalcLoading ? 'Recalculating...' : 'Recalculate Stats'}
					</button>
					{#if recalcMessage}
						<span class="recalc-message {recalcMessage.type}">{recalcMessage.text}</span>
					{/if}
				</div>
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
						<div class="col-who">
							{#if item.user}
								<a href="/user/{item.user.twitch_username}" class="activity-user">
									{#if item.user.twitch_avatar_url}
										<img src={item.user.twitch_avatar_url} alt="" class="activity-avatar" />
									{/if}
									<span class="activity-username"
										>{item.user.twitch_display_name || item.user.twitch_username}</span
									>
								</a>
							{/if}
							<span class="activity-date">{formatFullDate(item.date)}</span>
						</div>
						<div class="col-what">
							{#if item.type === 'race_participant' || item.type === 'race_organizer' || item.type === 'race_caster'}
								<a href="/race/{item.race_id}" class="activity-title">{item.race_name}</a>
							{:else if item.type === 'training'}
								<a href="/training/{item.session_id}" class="activity-title"
									>{item.pool_display_name || formatPoolName(item.pool_name)}</a
								>
							{/if}
						</div>
						<div class="col-context">
							<div class="badge-row">
								{#if item.type === 'race_participant'}
									<span class="activity-badge participant">Race</span>
								{:else if item.type === 'race_organizer'}
									<span class="activity-badge organizer">Organized</span>
								{:else if item.type === 'race_caster'}
									<span class="activity-badge caster">Casted</span>
								{:else if item.type === 'training'}
									<span class="activity-badge training">Solo</span>
								{/if}
								<span class="badge badge-{item.status}">{statusLabel(item.status)}</span>
								{#if item.type === 'training' && item.exclude_from_stats}
									<span class="badge badge-slow">Slow</span>
								{/if}
							</div>
							<div class="activity-details">
								{#if item.type === 'race_participant'}
									{#if item.placement}
										<span class="placement {placementClass(item.placement)}">
											{placementLabel(item.placement)} / {item.total_participants}
										</span>
									{/if}
									<span class="mono">{formatIgt(item.igt_ms)}</span>
									<span>{item.death_count} deaths</span>
								{:else if item.type === 'race_organizer'}
									<span>{item.participant_count} players</span>
								{:else if item.type === 'training'}
									<span class="mono">{formatIgt(item.igt_ms)}</span>
									<span>{item.death_count} deaths</span>
								{/if}
							</div>
						</div>
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
		width: 100%;
		max-width: 1200px;
		margin: 0 auto;
		padding: 2rem;
		box-sizing: border-box;
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

	.sort-btn {
		background: none;
		border: none;
		color: inherit;
		font: inherit;
		text-transform: inherit;
		letter-spacing: inherit;
		cursor: pointer;
		padding: 0;
		transition: color var(--transition);
		white-space: nowrap;
	}

	.sort-btn:hover {
		color: var(--color-purple);
	}

	.num-col .sort-btn {
		width: 100%;
		text-align: center;
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
		background: rgba(239, 68, 68, 0.15);
		color: var(--color-danger);
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
		gap: 0.35rem;
	}

	.activity-card {
		display: grid;
		grid-template-columns: 10rem 1fr auto;
		gap: 0.75rem;
		align-items: center;
		padding: 0.6rem 1rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
	}

	.col-who {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		min-width: 0;
	}

	.activity-user {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		text-decoration: none;
		color: inherit;
		min-width: 0;
	}

	.activity-user:hover .activity-username {
		color: var(--color-purple);
		text-decoration: underline;
	}

	.activity-avatar {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		border: 1px solid var(--color-border);
		flex-shrink: 0;
	}

	.activity-username {
		font-size: var(--font-size-sm);
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.activity-date {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		white-space: nowrap;
		padding-left: 1.75rem;
	}

	.col-what {
		min-width: 0;
	}

	.activity-title {
		color: var(--color-text-primary);
		text-decoration: none;
		font-weight: 600;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		display: block;
	}

	.activity-title:hover {
		color: var(--color-purple);
		text-decoration: underline;
	}

	.col-context {
		display: flex;
		flex-direction: column;
		align-items: flex-end;
		gap: 0.15rem;
		flex-shrink: 0;
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
		white-space: nowrap;
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

	.activity-details {
		display: flex;
		gap: 0.5rem;
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		white-space: nowrap;
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
		transition:
			background 0.15s,
			border-color 0.15s;
	}

	.btn-secondary:hover:not(:disabled) {
		border-color: var(--color-text-secondary);
	}

	.btn-secondary:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.section-title {
		font-size: var(--font-size-lg);
		font-weight: 600;
		color: var(--color-text);
		margin-bottom: 0.75rem;
	}

	.stats-description {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		margin-bottom: 1rem;
	}

	.stats-actions {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.action-btn.recalc {
		color: var(--color-warning, #d97706);
		border-color: var(--color-warning, #d97706);
	}

	.action-btn.recalc:hover:not(:disabled) {
		background: var(--color-warning, #d97706);
		color: white;
	}

	.recalc-message {
		font-size: var(--font-size-sm);
	}

	.recalc-message.success {
		color: var(--color-success, #22c55e);
	}

	.recalc-message.error {
		color: var(--color-danger, #ef4444);
	}

	.reported-section {
		margin-bottom: 2rem;
	}

	.reason-cell {
		max-width: 250px;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.link-btn {
		background: none;
		border: none;
		color: var(--color-purple);
		font-family: var(--font-family);
		font-size: inherit;
		cursor: pointer;
		padding: 0;
		text-decoration: underline;
	}

	.kpi-grid {
		display: grid;
		grid-template-columns: repeat(4, 1fr);
		gap: 0.75rem;
		margin-bottom: 1.5rem;
	}

	.kpi-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		padding: 1rem;
		text-align: center;
	}

	.kpi-label {
		font-size: var(--font-size-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
	}

	.kpi-value {
		font-size: 1.75rem;
		font-weight: 700;
		color: var(--color-text);
		margin: 0.25rem 0;
		font-variant-numeric: tabular-nums;
	}

	.kpi-gold {
		color: var(--color-gold);
	}

	.kpi-purple {
		color: var(--color-purple);
	}

	.kpi-sub {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
	}

	.charts-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.75rem;
		margin-bottom: 1.5rem;
	}

	.chart-box {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		padding: 1rem;
	}

	.chart-full {
		margin-bottom: 1.5rem;
	}

	.chart-title {
		font-size: var(--font-size-sm);
		font-weight: 600;
		color: var(--color-text);
		margin-bottom: 0.75rem;
	}

	.heatmaps-row {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 0.75rem;
		margin-bottom: 1.5rem;
	}

	.heatmap-box {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		padding: 1rem;
	}

	.heatmap-title {
		font-size: var(--font-size-sm);
		font-weight: 600;
		margin-bottom: 0.75rem;
	}

	.heatmap-gold {
		color: var(--color-gold);
	}

	.heatmap-purple {
		color: var(--color-purple);
	}

	.heatmap-tz {
		font-size: 0.65rem;
		font-weight: 400;
		color: var(--color-text-secondary);
		margin-left: 0.25rem;
	}

	.heatmap-grid {
		display: grid;
		grid-template-columns: 2.5rem repeat(7, 1fr);
		gap: 3px;
	}

	.heatmap-corner {
		display: block;
	}

	.heatmap-day {
		text-align: center;
		font-size: 0.6rem;
		color: var(--color-text-secondary);
		padding-bottom: 2px;
	}

	.heatmap-hour {
		text-align: right;
		padding-right: 4px;
		font-size: 0.6rem;
		color: var(--color-text-secondary);
		line-height: 1.5rem;
	}

	.heatmap-cell {
		height: 1.5rem;
		border-radius: 2px;
		background: var(--color-bg, #0d1117);
	}

	.heatmap-legend {
		display: flex;
		align-items: center;
		gap: 6px;
		margin-top: 0.5rem;
		font-size: 0.6rem;
		color: var(--color-text-secondary);
	}

	.heatmap-legend-bar {
		flex: 1;
		height: 8px;
		border-radius: 4px;
		max-width: 120px;
	}

	.heatmap-legend-gold {
		background: linear-gradient(to right, #0d1117, rgba(200, 164, 78, 0.9));
	}

	.heatmap-legend-purple {
		background: linear-gradient(to right, #0d1117, rgba(139, 92, 246, 0.9));
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
			display: flex;
			flex-direction: column;
			gap: 0.25rem;
		}

		.activity-date {
			padding-left: 0;
		}

		.col-context {
			align-items: flex-start;
		}

		.kpi-grid {
			grid-template-columns: repeat(2, 1fr);
		}

		.charts-grid,
		.heatmaps-row {
			grid-template-columns: 1fr;
		}
	}
</style>
