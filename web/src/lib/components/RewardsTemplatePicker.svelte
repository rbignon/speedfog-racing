<script lang="ts">
	import { onMount } from 'svelte';
	import {
		fetchMyInventory,
		patchEquipped,
		type MyInventoryDto,
		type NameTemplateDef
	} from '$lib/api';

	let inventory: MyInventoryDto | null = $state(null);
	let saving = $state(false);

	onMount(async () => {
		inventory = await fetchMyInventory();
	});

	async function activate(template_id: string) {
		if (!inventory) return;
		saving = true;
		const result = await patchEquipped({ equipped_name_template_id: template_id });
		if (result) {
			inventory.equipped_name_template_id = result.equipped_name_template_id;
		}
		saving = false;
	}

	function previewStyle(t: NameTemplateDef): string {
		if (t.gradient) {
			return `background: linear-gradient(90deg, ${t.gradient[0]}, ${t.gradient[1]}); -webkit-background-clip: text; background-clip: text; color: transparent;`;
		}
		if (t.color) {
			return `color: ${t.color};`;
		}
		return '';
	}

	function activeId(inv: MyInventoryDto): string {
		return inv.equipped_name_template_id ?? 'default';
	}
</script>

<section class="setting-field">
	<span class="field-label">Active Name Template</span>
	<p class="field-description">
		Choose a visual style for your username on the website and in-game leaderboards.
	</p>
	{#if !inventory}
		<p class="hint">Loading…</p>
	{:else}
		<ul class="rewards-list">
			{#each inventory.unlocked_templates as t (t.id)}
				<li
					class="rewards-item template-row"
					style={t.background_css ? `background: ${t.background_css};` : ''}
				>
					<span class="rewards-name preview" style={previewStyle(t)}>{t.name}</span>
					{#if activeId(inventory) === t.id}
						<span class="rewards-active">Active</span>
					{:else}
						<button class="btn btn-secondary" disabled={saving} onclick={() => activate(t.id)}>
							Activate
						</button>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}
</section>

<style>
	.rewards-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.rewards-item {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem 0.75rem;
		background: var(--color-bg);
		border-radius: var(--radius-sm);
	}

	.rewards-name {
		flex: 1;
		font-weight: 500;
	}

	.rewards-active {
		font-size: var(--font-size-sm);
		color: var(--color-gold, #ffd700);
	}

	.field-description {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		margin: 0.25rem 0 0.75rem;
	}

	.hint {
		color: var(--color-text-secondary);
	}
</style>
