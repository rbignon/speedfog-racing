<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { fetchLocales, updateLocale, updateOverlaySettings, type LocaleInfo } from '$lib/api';

	let locales = $state<LocaleInfo[]>([]);
	let selectedLocale = $state('en');
	let fontSize = $state(18);
	let saving = $state(false);
	let error = $state<string | null>(null);
	let success = $state(false);

	onMount(async () => {
		if (!auth.isLoggedIn) {
			goto('/');
			return;
		}
		locales = await fetchLocales();
		selectedLocale = auth.user?.locale ?? 'en';
		fontSize = auth.user?.overlay_settings?.font_size ?? 18;
	});

	async function handleSave() {
		saving = true;
		error = null;
		success = false;
		try {
			const [localeResult, overlayResult] = await Promise.all([
				updateLocale(selectedLocale),
				updateOverlaySettings({ font_size: fontSize })
			]);
			if (auth.user) {
				auth.user.locale = localeResult.locale;
				auth.user.overlay_settings = overlayResult.overlay_settings;
			}
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
		<h2>Language</h2>
		<p class="description">
			Choose the language for zone names and fog gate descriptions during races.
		</p>

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
					{#if locale.code !== 'en'}
						<span class="locale-code">({locale.code})</span>
					{/if}
				</label>
			{/each}
		</div>
	</section>

	<section class="setting-group">
		<h2>Overlay</h2>
		<p class="description">Customize the in-game overlay that displays race information.</p>

		<div class="setting-row">
			<label for="font-size">Font size</label>
			<div class="input-with-unit">
				<input id="font-size" type="number" min="8" max="72" step="1" bind:value={fontSize} />
				<span class="unit">px</span>
			</div>
			<span class="hint">8–72 px (default: 18)</span>
		</div>
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
		max-width: 640px;
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
		font-size: var(--font-size-lg);
		margin-bottom: 0.5rem;
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

	.locale-code {
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
	}

	.setting-row {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.setting-row label {
		font-size: var(--font-size-base);
		min-width: 5rem;
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
