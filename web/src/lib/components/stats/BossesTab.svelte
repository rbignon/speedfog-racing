<script lang="ts">
	import { fetchBossStats, type BossStatsResponse } from '$lib/api';
	import { formatIgt } from '$lib/utils/training';

	let data = $state<BossStatsResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	type SortKey = 'avg_deaths' | 'encounters' | 'max_deaths' | 'avg_time_ms' | 'display_name';
	let sortKey = $state<SortKey>('avg_deaths');
	let sortAsc = $state(false);

	let bosses = $derived.by(() => {
		const list = [...(data?.bosses ?? [])];
		list.sort((a, b) => {
			let cmp = 0;
			if (sortKey === 'display_name') {
				cmp = a.display_name.localeCompare(b.display_name);
			} else {
				cmp = a[sortKey] - b[sortKey];
			}
			return sortAsc ? cmp : -cmp;
		});
		return list;
	});

	$effect(() => {
		loadData();
	});

	async function loadData() {
		loading = true;
		error = null;
		try {
			data = await fetchBossStats();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load boss stats.';
		} finally {
			loading = false;
		}
	}

	function handleSort(key: SortKey) {
		if (sortKey === key) {
			sortAsc = !sortAsc;
		} else {
			sortKey = key;
			sortAsc = key === 'display_name';
		}
	}

	function sortIndicator(key: SortKey): string {
		if (sortKey !== key) return '';
		return sortAsc ? ' \u25B2' : ' \u25BC';
	}

	function typeBadgeClass(type: string): string {
		if (type === 'major') return 'boss-badge-major';
		return 'boss-badge-normal';
	}

	function typeLabel(type: string): string {
		if (type === 'major') return 'Major';
		return 'Boss';
	}
</script>

{#if loading}
	<p class="loading-text">Loading boss stats...</p>
{:else if error}
	<p class="error-text">{error}</p>
{:else}
	<div class="bosses-panel">
		<table class="bosses-table">
			<thead>
				<tr>
					<th>
						<button class="sort-btn" onclick={() => handleSort('display_name')}>
							Boss{sortIndicator('display_name')}
						</button>
					</th>
					<th class="th-num">
						<button class="sort-btn" onclick={() => handleSort('encounters')}>
							Encounters{sortIndicator('encounters')}
						</button>
					</th>
					<th class="th-num">
						<button class="sort-btn" onclick={() => handleSort('avg_deaths')}>
							Avg Deaths{sortIndicator('avg_deaths')}
						</button>
					</th>
					<th class="th-num">
						<button class="sort-btn" onclick={() => handleSort('max_deaths')}>
							Max Deaths{sortIndicator('max_deaths')}
						</button>
					</th>
					<th class="th-num">
						<button class="sort-btn" onclick={() => handleSort('avg_time_ms')}>
							Avg Time{sortIndicator('avg_time_ms')}
						</button>
					</th>
				</tr>
			</thead>
			<tbody>
				{#each bosses as boss}
					<tr>
						<td class="boss-cell">
							<span class="boss-name">{boss.display_name}</span>
							<span class="boss-badge {typeBadgeClass(boss.type)}">{typeLabel(boss.type)}</span>
						</td>
						<td class="num">{boss.encounters}</td>
						<td class="num">{boss.avg_deaths.toFixed(1)}</td>
						<td class="num">{boss.max_deaths}</td>
						<td class="num">{formatIgt(boss.avg_time_ms)}</td>
					</tr>
				{/each}
				{#if (data?.bosses ?? []).length === 0}
					<tr>
						<td colspan="5" class="empty-row">No boss data yet.</td>
					</tr>
				{/if}
			</tbody>
		</table>
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

	.bosses-panel {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		overflow-x: auto;
	}

	.bosses-table {
		width: 100%;
		border-collapse: collapse;
	}

	.bosses-table thead th {
		text-align: left;
		padding: 0.65rem 0.75rem;
		color: var(--color-text-secondary);
		font-weight: 500;
		font-size: var(--font-size-sm);
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 1px solid var(--color-border);
	}

	.th-num {
		text-align: right !important;
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

	.th-num .sort-btn {
		text-align: right;
		width: 100%;
		display: block;
	}

	.bosses-table tbody td {
		padding: 0.6rem 0.75rem;
		border-top: 1px solid var(--color-border);
	}

	.bosses-table tbody tr:first-child td {
		border-top: none;
	}

	.boss-cell {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.boss-name {
		font-weight: 500;
	}

	.boss-badge {
		font-size: 0.65rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 0.1rem 0.4rem;
		border-radius: var(--radius-sm);
	}

	.boss-badge-major {
		background: rgba(139, 92, 246, 0.2);
		color: var(--color-purple);
	}

	.boss-badge-normal {
		background: rgba(156, 163, 175, 0.15);
		color: var(--color-text-secondary);
	}

	.num {
		text-align: right;
		font-variant-numeric: tabular-nums;
	}

	.empty-row {
		text-align: center;
		color: var(--color-text-disabled);
		font-style: italic;
		padding: 2rem 0.75rem !important;
	}
</style>
