<script lang="ts">
	import type { UserPoolStatsEntry } from '$lib/api';
	import { formatIgt } from '$lib/utils/training';
	import { formatPoolName } from '$lib/utils/format';

	interface Props {
		pools: UserPoolStatsEntry[];
	}

	let { pools }: Props = $props();

	let maxRuns = $derived(
		Math.max(
			1,
			...pools.flatMap((p) => [p.race?.runs ?? 0, p.training?.runs ?? 0])
		)
	);

	function barWidth(runs: number): string {
		return `${Math.max(4, (runs / maxRuns) * 100)}%`;
	}
</script>

<div class="pool-stats-wrapper">
	<table class="pool-stats-table">
		<thead>
			<tr>
				<th>Pool</th>
				<th>Type</th>
				<th>Runs</th>
				<th>Avg Time</th>
				<th>Best Time</th>
				<th>Avg Deaths</th>
				<th class="bar-col"></th>
			</tr>
		</thead>
		<tbody>
			{#each pools as pool}
				<tr class="race-row">
					<td class="pool-name" rowspan={pool.training ? 2 : 1}>
						{formatPoolName(pool.pool_name)}
					</td>
					{#if pool.race}
						<td class="type-label race-type">Race</td>
						<td>{pool.race.runs}</td>
						<td>{formatIgt(pool.race.avg_time_ms)}</td>
						<td>{formatIgt(pool.race.best_time_ms)}</td>
						<td>{pool.race.avg_deaths.toFixed(1)}</td>
						<td class="bar-col">
							<div class="bar bar-race" style="width: {barWidth(pool.race.runs)}"></div>
						</td>
					{:else}
						<td class="type-label race-type">Race</td>
						<td class="dash">&mdash;</td>
						<td class="dash">&mdash;</td>
						<td class="dash">&mdash;</td>
						<td class="dash">&mdash;</td>
						<td class="bar-col"></td>
					{/if}
				</tr>
				{#if pool.training}
					<tr class="training-row">
						<td class="type-label training-type">Training</td>
						<td>{pool.training.runs}</td>
						<td>{formatIgt(pool.training.avg_time_ms)}</td>
						<td>{formatIgt(pool.training.best_time_ms)}</td>
						<td>{pool.training.avg_deaths.toFixed(1)}</td>
						<td class="bar-col">
							<div
								class="bar bar-training"
								style="width: {barWidth(pool.training.runs)}"
							></div>
						</td>
					</tr>
				{/if}
			{/each}
		</tbody>
	</table>
</div>

<style>
	.pool-stats-wrapper {
		overflow-x: auto;
		-webkit-overflow-scrolling: touch;
	}

	.pool-stats-table {
		width: 100%;
		border-collapse: collapse;
		font-size: 0.9rem;
	}

	thead th {
		text-align: left;
		padding: 0.5rem 0.75rem;
		color: var(--color-text-secondary);
		font-weight: 500;
		font-size: 0.8rem;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		border-bottom: 1px solid var(--color-border);
	}

	tbody td {
		padding: 0.4rem 0.75rem;
		color: var(--color-text);
	}

	.pool-name {
		font-weight: 600;
		color: var(--color-gold);
		vertical-align: middle;
	}

	.type-label {
		font-size: 0.8rem;
		font-weight: 500;
	}

	.race-type {
		color: var(--color-gold);
	}

	.training-type {
		color: var(--color-purple);
	}

	.dash {
		color: var(--color-text-disabled);
	}

	.race-row td {
		border-top: 1px solid var(--color-border);
	}

	.training-row td {
		border-top: none;
	}

	/* First pool group should not have a top border on the race row */
	tbody tr:first-child td {
		border-top: none;
	}

	.bar-col {
		width: 100px;
		min-width: 60px;
	}

	.bar {
		height: 6px;
		border-radius: 3px;
		transition: width 0.3s ease;
	}

	.bar-race {
		background: var(--color-gold);
	}

	.bar-training {
		background: var(--color-purple);
	}

	@media (max-width: 640px) {
		.bar-col {
			display: none;
		}

		thead th.bar-col {
			display: none;
		}
	}
</style>
