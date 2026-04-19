<script lang="ts">
	import type { PoolInfo } from '$lib/api';
	import { formatPoolName } from '$lib/utils/format';

	let {
		pools,
		selected,
		onselect,
		disabled = false,
		recommended = null
	}: {
		pools: [string, PoolInfo][];
		selected: string | null;
		onselect: (pool: string) => void;
		disabled?: boolean;
		recommended?: string | null;
	} = $props();
</script>

<div class="pool-tabs" role="tablist">
	{#each pools as [pool, info] (pool)}
		{@const isDisabled = info.available === 0 || disabled}
		<button
			type="button"
			class="pool-tab"
			class:active={selected === pool}
			class:disabled={isDisabled}
			disabled={isDisabled}
			role="tab"
			aria-selected={selected === pool}
			onclick={() => onselect(pool)}
		>
			{#if pool === recommended}
				<span class="badge-recommended">Recommended</span>
			{/if}
			<span class="pool-name">{info.pool_config?.name || formatPoolName(pool)}</span>
			{#if info.pool_config?.estimated_duration}
				<span class="pool-duration">{info.pool_config.estimated_duration}</span>
			{/if}
		</button>
	{/each}
</div>

<style>
	.pool-tabs {
		display: flex;
		flex-wrap: wrap;
		background: var(--color-border);
		row-gap: 1px;
		border-bottom: 1px solid var(--color-border);
	}

	.pool-tab {
		position: relative;
		flex: 1 1 0;
		min-width: 90px;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.1rem;
		padding: 0.65rem 0.5rem;
		background: var(--color-surface);
		border: none;
		border-right: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		font-weight: 500;
		cursor: pointer;
		transition: all var(--transition);
	}

	.pool-tab:last-child {
		border-right: none;
	}

	.pool-tab:hover:not(.disabled) {
		color: var(--color-text);
		background: var(--color-surface-elevated);
	}

	.pool-tab.active {
		background: var(--color-surface-elevated);
		color: var(--color-gold);
		box-shadow: inset 0 -2px 0 var(--color-gold);
	}

	.pool-tab.disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.pool-name {
		font-weight: 600;
	}

	.pool-duration {
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
	}

	.pool-tab.active .pool-duration {
		color: var(--color-text-secondary);
	}

	.badge-recommended {
		position: absolute;
		top: -0.9em;
		right: 0.4rem;
		font-size: 0.6rem;
		font-weight: 600;
		color: var(--color-gold);
		background: var(--color-surface-elevated);
		padding: 0.05em 0.45em;
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-gold);
		white-space: nowrap;
		line-height: 1.4;
	}

	@media (max-width: 640px) {
		.pool-tab {
			font-size: var(--font-size-xs);
			padding: 0.5rem 0.25rem;
		}
	}
</style>
