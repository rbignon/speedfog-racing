<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import {
		fetchLocales,
		fetchMyInventory,
		patchEquipped,
		updateLocale,
		updateOverlaySettings,
		type LocaleInfo,
		type MyInventoryDto
	} from '$lib/api';
	import { rewards } from '$lib/stores/rewards.svelte';
	import RewardsPicker from '$lib/components/RewardsPicker.svelte';

	let locales = $state<LocaleInfo[]>([]);
	let selectedLocale = $state('en');
	let fontSize = $state(18);
	let inventory = $state<MyInventoryDto | null>(null);
	let selectedTemplateId = $state('default');
	let selectedBadgeId = $state<string | null>(null);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let success = $state(false);

	onMount(async () => {
		if (!auth.isLoggedIn) {
			goto('/');
			return;
		}
		selectedLocale = auth.user?.locale ?? 'en';
		fontSize = auth.user?.overlay_settings?.font_size ?? 18;
		const [loadedLocales, loadedInventory] = await Promise.all([
			fetchLocales(),
			fetchMyInventory(),
			rewards.ensureLoaded().catch(() => undefined)
		]);
		locales = loadedLocales;
		inventory = loadedInventory;
		if (loadedInventory) {
			selectedTemplateId = loadedInventory.equipped_name_template_id ?? 'default';
			selectedBadgeId = loadedInventory.equipped_badge_id;
		}
	});

	async function handleSave() {
		saving = true;
		error = null;
		success = false;
		try {
			const calls: Promise<unknown>[] = [
				updateLocale(selectedLocale).then((r) => {
					if (auth.user) auth.user.locale = r.locale;
				}),
				updateOverlaySettings({ font_size: fontSize }).then((r) => {
					if (auth.user) auth.user.overlay_settings = r.overlay_settings;
				})
			];
			if (inventory) {
				calls.push(
					patchEquipped({
						equipped_name_template_id: selectedTemplateId,
						equipped_badge_id: selectedBadgeId
					}).then((result) => {
						if (!result || !inventory) return;
						inventory.equipped_name_template_id = result.equipped_name_template_id;
						inventory.equipped_badge_id = result.equipped_badge_id;
						if (auth.user) {
							auth.user.equipped_name_template_id = result.equipped_name_template_id;
							auth.user.equipped_badge_id = result.equipped_badge_id;
						}
					})
				);
			}
			await Promise.all(calls);
			success = true;
			setTimeout(() => (success = false), 3000);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to save';
		} finally {
			saving = false;
		}
	}
</script>

<svelte:head>
	<title>Settings – SpeedFog Racing</title>
</svelte:head>

<main class="settings">
	<h1>Settings</h1>

	<section class="setting-group">
		<h2>Overlay</h2>
		<p class="description">
			Customize the in-game overlay that displays race information. It automatically applies when
			you download seeds
		</p>

		<div class="setting-field">
			<label class="field-label" for="font-size">Font size</label>
			<p class="field-description">Size of the text displayed on the overlay.</p>
			<div class="setting-row">
				<div class="input-with-unit">
					<input id="font-size" type="number" min="8" max="72" step="1" bind:value={fontSize} />
					<span class="unit">px</span>
				</div>
				<span class="hint">8–72 px (default: 18)</span>
			</div>
		</div>

		<div class="setting-field">
			<span class="field-label">Language</span>
			<p class="field-description">Zone names and fog gate descriptions displayed in-game.</p>
			<div class="locale-select">
				{#each locales as locale}
					<label>
						<input
							type="radio"
							name="locale"
							value={locale.code}
							checked={selectedLocale === locale.code}
							onchange={() => (selectedLocale = locale.code)}
						/>
						{locale.name}
					</label>
				{/each}
			</div>
		</div>
	</section>

	<section class="setting-group" id="rewards">
		<h2>Rewards</h2>
		<p class="description">Pick a badge and a name template among the rewards you have unlocked.</p>

		{#if inventory && auth.user}
			<RewardsPicker {inventory} user={auth.user} bind:selectedTemplateId bind:selectedBadgeId />
		{:else}
			<p class="hint">Loading…</p>
		{/if}
	</section>

	<div class="actions">
		<button class="btn btn-primary" onclick={handleSave} disabled={saving}>
			{saving ? 'Saving...' : 'Save'}
		</button>
		{#if success}
			<span class="success-msg">Saved!</span>
		{/if}
		{#if error}
			<span class="error-msg">{error}</span>
		{/if}
	</div>
</main>

<style>
	.settings {
		max-width: 600px;
		margin: 0 auto;
		padding: 2rem 1.5rem;
	}

	h1 {
		font-size: var(--font-size-2xl);
		margin-bottom: 2rem;
	}

	.setting-group {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		padding: 1.5rem;
		margin-bottom: 1.5rem;
	}

	.setting-group h2 {
		margin-top: 0;
	}

	.description {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		margin-bottom: 1rem;
	}

	.locale-select {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.locale-select label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		font-size: var(--font-size-base);
	}

	.setting-field {
		margin-top: 1.25rem;
		padding-top: 1.25rem;
		border-top: 1px solid var(--color-border);
	}

	.field-label {
		font-size: var(--font-size-base);
		font-weight: 500;
		display: block;
		margin-bottom: 0.25rem;
	}

	.field-description {
		color: var(--color-text-secondary);
		font-size: var(--font-size-xs);
		margin-bottom: 0.75rem;
	}

	.setting-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.input-with-unit {
		display: flex;
		align-items: center;
		gap: 0.25rem;
	}

	.input-with-unit input {
		width: 5rem;
		padding: 0.375rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-bg);
		color: var(--color-text);
		font-size: var(--font-size-base);
	}

	.unit {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
	}

	.hint {
		color: var(--color-text-disabled);
		font-size: var(--font-size-xs);
	}

	.actions {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.success-msg {
		color: var(--color-green);
		font-size: var(--font-size-sm);
	}

	.error-msg {
		color: var(--color-danger);
		font-size: var(--font-size-sm);
	}
</style>
