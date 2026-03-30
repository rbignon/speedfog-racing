<script lang="ts">
	import { fetchLeaderboard, type LeaderboardResponse } from '$lib/api';

	let data = $state<LeaderboardResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let players = $derived(data?.players ?? []);
	let community = $derived(data?.community ?? null);

	$effect(() => {
		loadData();
	});

	async function loadData() {
		loading = true;
		error = null;
		try {
			data = await fetchLeaderboard();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load leaderboard.';
		} finally {
			loading = false;
		}
	}

	function formatHours(h: number): string {
		if (h < 1) return '<1';
		return h.toFixed(0);
	}

	const CONFIDENCE_THRESHOLD = 20;

	function confidenceLevel(races: number): 'high' | 'medium' | 'low' {
		const pct = Math.min(100, (races / CONFIDENCE_THRESHOLD) * 100);
		if (pct >= 75) return 'high';
		if (pct >= 40) return 'medium';
		return 'low';
	}

	function confidenceLabel(races: number): string {
		const pct = Math.min(100, Math.round((races / CONFIDENCE_THRESHOLD) * 100));
		return `Rating confidence: ${pct}% (${races} races)`;
	}
</script>

{#if loading}
	<p class="loading-text">Loading leaderboard...</p>
{:else if error}
	<p class="error-text">{error}</p>
{:else}
	<div class="leaderboard-layout">
		<div class="ranking-panel">
			<table class="ranking-table">
				<thead>
					<tr>
						<th class="th-rank">#</th>
						<th>Player</th>
						<th class="th-num">ELO</th>
						<th class="th-num">Races</th>
						<th class="th-num">Trend</th>
					</tr>
				</thead>
				<tbody>
					{#each players as player, i}
						<tr>
							<td class="rank" class:rank-gold={i === 0}>
								{i + 1}
							</td>
							<td class="player-cell">
								{#if player.twitch_avatar_url}
									<img src={player.twitch_avatar_url} alt="" class="player-avatar" />
								{:else}
									<div class="player-avatar-placeholder"></div>
								{/if}
								<a href="/user/{player.twitch_username}" class="player-name">
									{player.twitch_display_name || player.twitch_username}
								</a>
							</td>
							<td class="num elo-value">
								<span class="elo-content">
									{player.elo_rating}<span
										class="confidence-dot confidence-{confidenceLevel(player.elo_races)}"
										title={confidenceLabel(player.elo_races)}
									></span>
								</span>
							</td>
							<td class="num">{player.elo_races}</td>
							<td class="num">
								{#if player.trend_delta > 0}
									<span class="trend-up">+{player.trend_delta}</span>
								{:else if player.trend_delta < 0}
									<span class="trend-down">{player.trend_delta}</span>
								{:else}
									<span class="trend-neutral">0</span>
								{/if}
							</td>
						</tr>
					{/each}
					{#if players.length === 0}
						<tr>
							<td colspan="5" class="empty-row">No ranked players yet.</td>
						</tr>
					{/if}
				</tbody>
			</table>
		</div>

		<aside class="sidebar">
			{#if community}
				<div class="sidebar-card">
					<h3>Community</h3>
					<dl class="stat-list">
						<div class="stat-row">
							<dt>Total races</dt>
							<dd>{community.total_races}</dd>
						</div>
						<div class="stat-row">
							<dt>Active players</dt>
							<dd>{community.active_players}</dd>
						</div>
						<div class="stat-row">
							<dt>Ranked players</dt>
							<dd>{community.ranked_players}</dd>
						</div>
						<div class="stat-row">
							<dt>Total deaths</dt>
							<dd>{community.total_deaths.toLocaleString()}</dd>
						</div>
						<div class="stat-row">
							<dt>Hours raced</dt>
							<dd>{formatHours(community.hours_raced)}</dd>
						</div>
					</dl>
				</div>
			{/if}

			<div class="sidebar-card">
				<h3>How ELO works</h3>
				<dl class="elo-details">
					<div class="elo-detail-row">
						<dt>Starting rating</dt>
						<dd>1500</dd>
					</div>
					<div class="elo-detail-row">
						<dt>Min. public races</dt>
						<dd>3</dd>
					</div>
				</dl>
				<p class="elo-explanation">
					After each race, points are exchanged based on finish order and time gaps. Beating
					higher-rated players earns more. Harder seeds give a small bonus to all participants.
				</p>
				<p class="elo-explanation">
					Rankings factor in confidence: when two players have similar ratings, the one with more
					races ranks higher.
				</p>
				<div class="confidence-legend">
					<span class="legend-item">
						<span class="confidence-dot confidence-high"></span> Established (15+)
					</span>
					<span class="legend-item">
						<span class="confidence-dot confidence-medium"></span> Settling (8-14)
					</span>
					<span class="legend-item">
						<span class="confidence-dot confidence-low"></span> Provisional (3-7)
					</span>
				</div>
			</div>
		</aside>
	</div>
{/if}

<style>
	.loading-text,
	.error-text {
		color: var(--color-text-disabled);
		font-style: italic;
		padding: 2rem 0;
	}

	.error-text {
		color: var(--color-danger);
	}

	.leaderboard-layout {
		display: grid;
		grid-template-columns: 1fr 300px;
		gap: 1.5rem;
		align-items: start;
	}

	.ranking-panel {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		overflow-x: auto;
	}

	.ranking-table {
		width: 100%;
		border-collapse: collapse;
	}

	.ranking-table thead th {
		text-align: left;
		padding: 0.65rem 0.75rem;
		color: var(--color-text-secondary);
		font-weight: 500;
		font-size: var(--font-size-sm);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 1px solid var(--color-border);
	}

	.th-rank {
		width: 3rem;
	}

	.th-num {
		text-align: right !important;
	}

	.ranking-table tbody td {
		padding: 0.6rem 0.75rem;
		border-top: 1px solid var(--color-border);
	}

	.ranking-table tbody tr:first-child td {
		border-top: none;
	}

	.rank {
		color: var(--color-text-secondary);
		font-variant-numeric: tabular-nums;
		font-weight: 600;
	}

	.rank-gold {
		color: var(--color-gold);
	}

	.elo-content {
		display: inline-flex;
		align-items: center;
		justify-content: flex-end;
		gap: 0.35rem;
	}

	.confidence-dot {
		display: inline-block;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.confidence-high {
		background: var(--color-success);
	}

	.confidence-medium {
		background: var(--color-warning);
	}

	.confidence-low {
		background: var(--color-text-disabled);
	}

	.player-cell {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.player-avatar {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		object-fit: cover;
		flex-shrink: 0;
	}

	.player-avatar-placeholder {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--color-surface-elevated);
		flex-shrink: 0;
	}

	.player-name {
		color: var(--color-text);
		text-decoration: none;
		font-weight: 500;
		transition: color var(--transition);
	}

	.player-name:hover {
		color: var(--color-purple);
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.elo-value {
		font-weight: 700;
	}

	.trend-up {
		color: var(--color-success);
	}

	.trend-down {
		color: var(--color-danger);
	}

	.trend-neutral {
		color: var(--color-text-disabled);
	}

	.empty-row {
		text-align: center;
		color: var(--color-text-disabled);
		font-style: italic;
		padding: 2rem 0.75rem !important;
	}

	.sidebar {
		display: flex;
		flex-direction: column;
		gap: 1rem;
	}

	.sidebar-card {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 1rem 1.25rem;
	}

	.sidebar-card h3 {
		margin: 0 0 0.75rem 0;
		font-size: var(--font-size-base);
		font-weight: 600;
		color: var(--color-text);
	}

	.stat-list {
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.stat-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.stat-row dt {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
	}

	.stat-row dd {
		margin: 0;
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.elo-details {
		margin: 0 0 0.6rem 0;
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.elo-detail-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.elo-detail-row dt {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
	}

	.elo-detail-row dd {
		margin: 0;
		font-weight: 600;
		font-size: var(--font-size-sm);
		font-variant-numeric: tabular-nums;
	}

	.elo-explanation {
		margin: 0 0 0.5rem 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
		line-height: 1.5;
	}

	.elo-explanation:last-of-type {
		margin-bottom: 0;
	}

	.confidence-legend {
		display: flex;
		gap: 0.75rem;
		margin-top: 0.6rem;
		flex-wrap: wrap;
	}

	.legend-item {
		display: inline-flex;
		align-items: center;
		gap: 0.3rem;
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
	}

	@media (max-width: 768px) {
		.leaderboard-layout {
			grid-template-columns: 1fr;
		}

		.sidebar {
			flex-direction: row;
			flex-wrap: wrap;
		}

		.sidebar-card {
			flex: 1;
			min-width: 200px;
		}
	}
</style>
