<script lang="ts">
	import type { TrainingSession } from '$lib/api';
	import { displayPoolName, formatIgt } from '$lib/utils/training';
	import { timeAgo } from '$lib/utils/time';

	let { session }: { session: TrainingSession } = $props();
</script>

<a href="/training/{session.id}" class="card border-active">
	<div class="card-header">
		<span class="card-title">{displayPoolName(session.pool_name)}</span>
		<span class="badge badge-{session.status}">{session.status}</span>
	</div>

	<div class="card-stats">
		<span class="stat">
			<span class="stat-label">IGT</span>
			<span class="stat-value">{formatIgt(session.igt_ms)}</span>
		</span>
		<span class="stat">
			<span class="stat-label">Deaths</span>
			<span class="stat-value">{session.death_count}</span>
		</span>
	</div>

	{#if session.current_layer != null && session.seed_total_layers}
		<div class="progress-bar">
			<div
				class="progress-fill"
				style="width: {(session.current_layer / session.seed_total_layers) * 100}%"
			></div>
		</div>
	{/if}

	<div class="card-meta">
		<span>{timeAgo(session.created_at)}</span>
		<span class="action-label">Resume &rarr;</span>
	</div>
</a>

<style>
	.card {
		display: block;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 1rem 1.25rem;
		text-decoration: none;
		color: inherit;
		transition:
			border-color var(--transition),
			box-shadow var(--transition);
	}

	.card:hover {
		border-color: var(--color-purple);
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
	}

	.border-active {
		border-left: 3px solid var(--color-gold);
	}

	.card-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}

	.card-title {
		font-size: 1.05rem;
		font-weight: 500;
	}

	.card-stats {
		display: flex;
		gap: 1.5rem;
		margin-bottom: 0.5rem;
	}

	.stat {
		display: flex;
		flex-direction: column;
		gap: 0.1rem;
	}

	.stat-label {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 500;
	}

	.stat-value {
		font-weight: 600;
		font-variant-numeric: tabular-nums;
	}

	.progress-bar {
		height: 4px;
		background: var(--color-border);
		border-radius: 2px;
		overflow: hidden;
		margin-bottom: 0.5rem;
	}

	.progress-fill {
		height: 100%;
		background: var(--color-purple);
		border-radius: 2px;
		transition: width 0.3s ease;
	}

	.card-meta {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.action-label {
		color: var(--color-purple);
		font-weight: 500;
	}
</style>
