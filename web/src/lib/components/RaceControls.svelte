<script lang="ts">
	import { goto } from '$app/navigation';
	import {
		openRace,
		generateSeedPacks,
		startRace,
		resetRace,
		finishRace,
		deleteRace,
		fetchRace,
		type RaceDetail
	} from '$lib/api';

	interface Props {
		race: RaceDetail;
		raceStatus: string;
		onRaceUpdated: (race: RaceDetail) => void;
	}

	let { race, raceStatus, onRaceUpdated }: Props = $props();

	let loading = $state(false);
	let error = $state<string | null>(null);
	let showDeleteConfirm = $state(false);

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

	async function handleReset() {
		if (!confirm('Reset this race? All participant progress will be cleared.')) return;
		loading = true;
		error = null;
		try {
			await resetRace(race.id);
			const updated = await fetchRace(race.id);
			onRaceUpdated(updated);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to reset race';
		} finally {
			loading = false;
		}
	}

	async function handleForceFinish() {
		if (
			!confirm(
				'Force finish this race? Non-finished participants will keep their current progress.'
			)
		)
			return;
		loading = true;
		error = null;
		try {
			await finishRace(race.id);
			const updated = await fetchRace(race.id);
			onRaceUpdated(updated);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to finish race';
		} finally {
			loading = false;
		}
	}

	async function handleDelete() {
		loading = true;
		error = null;
		try {
			await deleteRace(race.id);
			goto('/');
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to delete race';
			showDeleteConfirm = false;
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
	{:else if raceStatus === 'running'}
		<button class="btn btn-primary btn-full" onclick={handleForceFinish} disabled={loading}>
			{loading ? 'Finishing...' : 'Force Finish'}
		</button>
		<p class="hint">End the race now. Unfinished participants keep their current progress.</p>

		<button class="btn btn-secondary btn-full" onclick={handleReset} disabled={loading}>
			{loading ? 'Resetting...' : 'Reset Race'}
		</button>
		<p class="hint">Clear all progress and return to OPEN status.</p>
	{:else if raceStatus === 'finished'}
		<button class="btn btn-secondary btn-full" onclick={handleReset} disabled={loading}>
			{loading ? 'Resetting...' : 'Reset Race'}
		</button>
		<p class="hint">Clear all progress and return to OPEN status for a re-run.</p>
	{/if}

	<div class="danger-zone">
		{#if showDeleteConfirm}
			<p class="delete-warning">
				This will permanently delete the race and all data. This cannot be undone.
			</p>
			<div class="delete-actions">
				<button class="btn btn-danger" onclick={handleDelete} disabled={loading}>
					{loading ? 'Deleting...' : 'Confirm Delete'}
				</button>
				<button
					class="btn btn-secondary"
					onclick={() => (showDeleteConfirm = false)}
					disabled={loading}
				>
					Cancel
				</button>
			</div>
		{:else}
			<button
				class="btn-delete-link"
				onclick={() => (showDeleteConfirm = true)}
				disabled={loading}
			>
				Delete Race
			</button>
		{/if}
	</div>
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
		margin: 0 0 0.5rem 0;
		line-height: 1.4;
	}

	.error {
		color: var(--color-danger);
		font-size: var(--font-size-sm);
		margin: 0 0 0.5rem 0;
	}

	.danger-zone {
		margin-top: 1rem;
		padding-top: 1rem;
		border-top: 1px solid var(--color-border);
	}

	.delete-warning {
		color: var(--color-danger);
		font-size: var(--font-size-xs);
		margin: 0 0 0.5rem 0;
		line-height: 1.4;
	}

	.delete-actions {
		display: flex;
		gap: 0.5rem;
	}

	.delete-actions .btn {
		flex: 1;
	}

	.btn-delete-link {
		background: none;
		border: none;
		color: var(--color-text-disabled);
		font-family: var(--font-family);
		font-size: var(--font-size-xs);
		cursor: pointer;
		padding: 0;
		text-decoration: underline;
		transition: color var(--transition);
	}

	.btn-delete-link:hover {
		color: var(--color-danger);
	}

	.btn-delete-link:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
