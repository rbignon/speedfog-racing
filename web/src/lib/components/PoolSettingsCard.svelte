<script lang="ts">
	import type { PoolConfig } from '$lib/api';
	import { formatPoolName } from '$lib/utils/format';

	let {
		poolName,
		poolConfig,
		compact = false
	}: {
		poolName: string;
		poolConfig: PoolConfig;
		compact?: boolean;
	} = $props();

	let title = $derived(formatPoolName(poolName));

	let miscNotes = $derived.by(() => {
		const notes: string[] = [];
		if (poolConfig.nerf_gargoyles === true) {
			notes.push('Gargoyle poison disabled');
		}
		return notes;
	});
</script>

<div class="card" class:compact>
	<h3 class="title">{title}</h3>
	{#if poolConfig.description}
		<p class="description">{poolConfig.description}</p>
	{/if}
	<div class="info-grid">
		{#if poolConfig.estimated_duration}
			<div class="info-item">
				<span class="label">Est. Duration</span>
				<span class="value">{poolConfig.estimated_duration}</span>
			</div>
		{/if}
		{#if poolConfig.legacy_dungeons != null && poolConfig.legacy_dungeons > 0}
			<div class="info-item">
				<span class="label">Legacy Dungeons</span>
				<span class="value">{poolConfig.legacy_dungeons}</span>
			</div>
		{/if}
		{#if poolConfig.min_layers != null && poolConfig.max_layers != null}
			<div class="info-item">
				<span class="label">Layers</span>
				<span class="value">{poolConfig.min_layers}–{poolConfig.max_layers}</span>
			</div>
		{/if}
		{#if poolConfig.final_tier != null}
			<div class="info-item">
				<span class="label">Final Tier</span>
				<span class="value">{poolConfig.final_tier}</span>
			</div>
		{/if}
		{#if poolConfig.care_package && poolConfig.weapon_upgrade != null}
			<div class="info-item">
				<span class="label">Care Package</span>
				<span class="value">{poolConfig.weapon_upgrade === 0 ? 'Yes' : `+${poolConfig.weapon_upgrade} upgrade`}</span>
			</div>
		{/if}
		{#if poolConfig.items_randomized != null}
			<div class="info-item">
				<span class="label">Items Randomized</span>
				<span class="value">{poolConfig.items_randomized ? 'Yes' : 'No'}</span>
			</div>
		{/if}
		{#if poolConfig.auto_upgrade_weapons}
			<div class="info-item">
				<span class="label">Auto Upgrade</span>
				<span class="value">Yes</span>
			</div>
		{/if}
		{#if poolConfig.remove_requirements}
			<div class="info-item">
				<span class="label">No Stat Reqs</span>
				<span class="value">Yes</span>
			</div>
		{/if}
		{#if poolConfig.item_difficulty}
			<div class="info-item">
				<span class="label">Item Difficulty</span>
				<span class="value">{poolConfig.item_difficulty}</span>
			</div>
		{/if}
		{#if poolConfig.major_boss_ratio}
			<div class="info-item">
				<span class="label">Major Bosses</span>
				<span class="value">{poolConfig.major_boss_ratio}</span>
			</div>
		{/if}
		{#if poolConfig.randomize_bosses}
			<div class="info-item">
				<span class="label">Boss Shuffle</span>
				<span class="value">Yes</span>
			</div>
		{/if}
	</div>
	{#if poolConfig.starting_items}
		<div class="item-section">
			<span class="label">Starting Items</span>
			{#if compact}
				<span class="item-section-text">{poolConfig.starting_items.join(', ')}</span>
			{:else}
				<ul class="item-section-list">
					{#each poolConfig.starting_items as item}
						<li>{item}</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
	{#if poolConfig.care_package_items}
		<div class="item-section">
			<span class="label">Care Package Contents</span>
			{#if compact}
				<span class="item-section-text">{poolConfig.care_package_items.join(', ')}</span>
			{:else}
				<ul class="item-section-list">
					{#each poolConfig.care_package_items as item}
						<li>{item}</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
	{#if miscNotes.length > 0}
		<div class="item-section">
			<span class="label">Misc</span>
			{#if compact}
				<span class="item-section-text">{miscNotes.join(', ')}</span>
			{:else}
				<ul class="item-section-list">
					{#each miscNotes as note}
						<li>{note}</li>
					{/each}
				</ul>
			{/if}
		</div>
	{/if}
</div>

<style>
	.card {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 1.5rem;
	}

	.card.compact {
		padding: 1rem;
	}

	.title {
		color: var(--color-gold);
		font-size: var(--font-size-lg);
		font-weight: 600;
		margin: 0 0 0.25rem 0;
	}

	.card.compact .title {
		font-size: var(--font-size-base);
	}

	.description {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		margin: 0 0 1rem 0;
	}

	.info-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 1rem;
	}

	.card.compact .info-grid {
		grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
	}

	.info-item {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.label {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 500;
	}

	.value {
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}

	.item-section {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		margin-top: 1rem;
		padding-top: 1rem;
		border-top: 1px solid var(--color-border);
	}

	.item-section-text {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.item-section-list {
		list-style: none;
		margin: 0.25rem 0 0 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
	}

	.item-section-list li {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}
</style>
