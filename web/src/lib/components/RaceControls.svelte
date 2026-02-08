<script lang="ts">
	import { openRace, generateSeedPacks, startRace, fetchRace, type RaceDetail } from '$lib/api';

	interface Props {
		race: RaceDetail;
		raceStatus: string;
		onRaceUpdated: (race: RaceDetail) => void;
	}

	let { race, raceStatus, onRaceUpdated }: Props = $props();

	let loading = $state(false);
	let error = $state<string | null>(null);

	let allHaveSeedPack = $derived(
		race.participants.length > 0 && race.participants.every((p) => p.has_seed_pack)
	);

	async function handleOpen() {
		loading = true;
		error = null;
		try {
			await openRace(race.id);
			const updated = await fetchRace(race.id);
			onRaceUpdated(updated);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to open race';
		} finally {
			loading = false;
		}
	}

	async function handleGeneratePacks() {
		loading = true;
		error = null;
		try {
			await generateSeedPacks(race.id);
			const updated = await fetchRace(race.id);
			onRaceUpdated(updated);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to generate seed packs';
		} finally {
			loading = false;
		}
	}

	async function handleStart() {
		loading = true;
		error = null;
		try {
			await startRace(race.id);
			const updated = await fetchRace(race.id);
			onRaceUpdated(updated);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to start race';
		} finally {
			loading = false;
		}
	}
</script>

<div class="race-controls">
	<h3>Race Controls</h3>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if raceStatus === 'draft'}
		<button class="btn btn-primary btn-full" onclick={handleOpen} disabled={loading}>
			{loading ? 'Opening...' : 'Open Race'}
		</button>
		<p class="hint">Open the race to finalize participants and generate seed packs.</p>
	{:else if raceStatus === 'open'}
		{#if allHaveSeedPack}
			<button class="btn btn-secondary btn-full" disabled>Seed Packs Generated</button>
		{:else}
			<button
				class="btn btn-secondary btn-full"
				onclick={handleGeneratePacks}
				disabled={loading || race.participants.length === 0}
			>
				{loading ? 'Generating...' : 'Generate Seed Packs'}
			</button>
		{/if}

		<button class="btn btn-primary btn-full" onclick={handleStart} disabled={loading}>
			{loading ? 'Starting...' : 'Start Race'}
		</button>
	{/if}
</div>

<style>
	.race-controls {
		padding-top: 1rem;
		border-top: 1px solid var(--color-border);
	}

	h3 {
		color: var(--color-text-secondary);
		margin: 0 0 0.75rem 0;
		font-size: var(--font-size-sm);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.btn-full {
		width: 100%;
		margin-bottom: 0.5rem;
	}

	.hint {
		color: var(--color-text-disabled);
		font-size: var(--font-size-xs);
		margin: 0;
		line-height: 1.4;
	}

	.error {
		color: var(--color-danger);
		font-size: var(--font-size-sm);
		margin: 0 0 0.5rem 0;
	}
</style>
