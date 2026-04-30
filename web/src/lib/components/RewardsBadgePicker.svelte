<script lang="ts">
	import { onMount } from 'svelte';
	import { fetchMyInventory, patchEquipped, type MyInventoryDto } from '$lib/api';

	let inventory: MyInventoryDto | null = $state(null);
	let saving = $state(false);

	onMount(async () => {
		inventory = await fetchMyInventory();
	});

	async function equip(badge_id: string | null) {
		if (!inventory) return;
		saving = true;
		const result = await patchEquipped({ equipped_badge_id: badge_id });
		if (result) {
			inventory.equipped_badge_id = result.equipped_badge_id;
		}
		saving = false;
	}
</script>

<section class="setting-field">
	<span class="field-label">Active Badge</span>
	<p class="field-description">
		Choose a badge to display next to your name in races and on the leaderboard.
	</p>
	{#if !inventory}
		<p class="hint">Loading…</p>
	{:else if inventory.held_badges.length === 0}
		<p class="hint">You have not earned any badge yet.</p>
	{:else}
		<ul class="rewards-list">
			{#each inventory.held_badges as badge (badge.id)}
				<li class="rewards-item">
					<img src="/badges/{badge.icon_filename}" alt="" class="rewards-icon" />
					<span class="rewards-name">{badge.name}</span>
					{#if inventory.equipped_badge_id === badge.id}
						<span class="rewards-active">Active</span>
						<button class="btn btn-secondary" disabled={saving} onclick={() => equip(null)}>
							Clear
						</button>
					{:else}
						<button class="btn btn-secondary" disabled={saving} onclick={() => equip(badge.id)}>
							Equip
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

	.rewards-icon {
		width: 24px;
		height: 24px;
	}

	.rewards-name {
		flex: 1;
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
