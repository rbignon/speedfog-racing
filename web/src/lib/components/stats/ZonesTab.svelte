<script lang="ts">
	import { fetchZoneStats, type ZoneStatsResponse } from '$lib/api';

	let data = $state<ZoneStatsResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);

	let deadliest = $derived(data?.deadliest ?? []);
	let mostVisited = $derived(data?.most_visited ?? []);

	let maxDeaths = $derived(Math.max(1, ...deadliest.map((z) => z.total_deaths)));
	let maxVisitRate = $derived(Math.max(1, ...mostVisited.map((z) => z.visit_rate)));

	$effect(() => {
		loadData();
	});

	async function loadData() {
		loading = true;
		error = null;
		try {
			data = await fetchZoneStats();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load zone stats.';
		} finally {
			loading = false;
		}
	}

	function deathBarWidth(deaths: number): string {
		return `${Math.max(4, (deaths / maxDeaths) * 100)}%`;
	}

	function visitBarWidth(rate: number): string {
		return `${Math.max(4, (rate / maxVisitRate) * 100)}%`;
	}

	function typeBadgeClass(type: string): string {
		if (type === 'legacy_dungeon') return 'type-badge-legacy';
		return 'type-badge-mini';
	}

	function typeLabel(type: string): string {
		if (type === 'legacy_dungeon') return 'Legacy';
		return 'Mini';
	}
</script>

{#if loading}
	<p class="loading-text">Loading zone stats...</p>
{:else if error}
	<p class="error-text">{error}</p>
{:else}
	<div class="zones-layout">
		<div class="zone-panel">
			<h2>Deadliest Zones</h2>
			{#if deadliest.length === 0}
				<p class="empty">No data yet.</p>
			{:else}
				<div class="zone-list">
					{#each deadliest as zone}
						<div class="zone-row">
							<div class="zone-header">
								<span class="zone-name">{zone.display_name}</span>
								<span class="type-badge {typeBadgeClass(zone.type)}">{typeLabel(zone.type)}</span>
							</div>
							<div class="bar-row">
								<div class="bar bar-death" style="width: {deathBarWidth(zone.total_deaths)}"></div>
								<span class="bar-value">{zone.total_deaths}</span>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>

		<div class="zone-panel">
			<h2>Most Visited Zones</h2>
			{#if mostVisited.length === 0}
				<p class="empty">No data yet.</p>
			{:else}
				<div class="zone-list">
					{#each mostVisited as zone}
						<div class="zone-row">
							<div class="zone-header">
								<span class="zone-name">{zone.display_name}</span>
								<span class="type-badge {typeBadgeClass(zone.type)}">{typeLabel(zone.type)}</span>
							</div>
							<div class="bar-row">
								<div class="bar bar-visit" style="width: {visitBarWidth(zone.visit_rate)}"></div>
								<span class="bar-value">{(zone.visit_rate * 100).toFixed(0)}%</span>
							</div>
						</div>
					{/each}
				</div>
			{/if}
		</div>
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

	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.zones-layout {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1.5rem;
	}

	.zone-panel {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 1.25rem;
	}

	.zone-panel h2 {
		margin: 0 0 1rem 0;
		font-size: var(--font-size-lg);
		font-weight: 600;
		color: var(--color-gold);
	}

	.zone-list {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.zone-row {
		display: flex;
		flex-direction: column;
		gap: 0.3rem;
	}

	.zone-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.zone-name {
		font-weight: 500;
		font-size: var(--font-size-base);
	}

	.type-badge {
		font-size: 0.65rem;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		padding: 0.1rem 0.4rem;
		border-radius: var(--radius-sm);
	}

	.type-badge-legacy {
		background: rgba(200, 164, 78, 0.2);
		color: var(--color-gold);
	}

	.type-badge-mini {
		background: rgba(107, 114, 128, 0.2);
		color: var(--color-text-secondary);
	}

	.bar-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.bar {
		height: 10px;
		border-radius: 5px;
		transition: width 0.3s ease;
	}

	.bar-death {
		background: var(--color-danger);
	}

	.bar-visit {
		background: var(--color-purple);
	}

	.bar-value {
		font-size: var(--font-size-sm);
		font-variant-numeric: tabular-nums;
		color: var(--color-text-secondary);
		flex-shrink: 0;
	}

	@media (max-width: 768px) {
		.zones-layout {
			grid-template-columns: 1fr;
		}
	}
</style>
