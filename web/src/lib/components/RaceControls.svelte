<script lang="ts">
	import {
		releaseSeeds,
		rerollSeed,
		startRace,
		resetRace,
		finishRace,
		fetchRace,
		type RaceDetail
	} from '$lib/api';
	import ConfirmModal from './ConfirmModal.svelte';

	interface Props {
		race: RaceDetail;
		raceStatus: string;
		onRaceUpdated: (race: RaceDetail) => void;
	}

	let { race, raceStatus, onRaceUpdated }: Props = $props();

	let loading = $state(false);
	let error = $state<string | null>(null);
	let seedsReleased = $derived(race.seeds_released_at !== null);

	let pendingConfirm = $state<{
		title: string;
		message: string;
		confirmLabel: string;
		danger?: boolean;
		action: () => Promise<void>;
	} | null>(null);

	function requestConfirm(opts: NonNullable<typeof pendingConfirm>) {
		pendingConfirm = opts;
	}

	async function executeConfirm() {
		if (!pendingConfirm) return;
		const action = pendingConfirm.action;
		pendingConfirm = null;
		await action();
	}

	async function handleRelease() {
		loading = true;
		error = null;
		try {
			const updated = await releaseSeeds(race.id);
			onRaceUpdated(updated);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to release seeds';
		} finally {
			loading = false;
		}
	}

	function handleReroll() {
		requestConfirm({
			title: 'Re-roll Seed',
			message: seedsReleased
				? 'Participants may have already downloaded. Re-rolling will require everyone to re-download. Continue?'
				: 'Re-roll the seed? Participants will need to download a new seed pack.',
			confirmLabel: 'Re-roll',
			async action() {
				loading = true;
				error = null;
				try {
					const updated = await rerollSeed(race.id);
					onRaceUpdated(updated);
				} catch (e) {
					error = e instanceof Error ? e.message : 'Failed to re-roll seed';
				} finally {
					loading = false;
				}
			}
		});
	}

	function handleStart() {
		requestConfirm({
			title: 'Start Race',
			message: 'Start the race? All participants will be notified.',
			confirmLabel: 'Start',
			async action() {
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
		});
	}

	function handleReset() {
		requestConfirm({
			title: 'Reset Race',
			message: 'Reset this race? All participant progress will be cleared.',
			confirmLabel: 'Reset',
			danger: true,
			async action() {
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
		});
	}

	function handleForceFinish() {
		requestConfirm({
			title: 'Force Finish',
			message:
				'Force finish this race? Non-finished participants will keep their current progress.',
			confirmLabel: 'Force Finish',
			async action() {
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
		});
	}
</script>

<div class="race-controls">
	<h3>Race Controls</h3>

	{#if error}
		<p class="error">{error}</p>
	{/if}

	{#if raceStatus === 'setup'}
		{#if seedsReleased}
			<button class="btn btn-primary btn-full" onclick={handleStart} disabled={loading}>
				{loading ? 'Starting...' : 'Start Race'}
			</button>
		{:else}
			<button class="btn btn-primary btn-full" onclick={handleRelease} disabled={loading}>
				{loading ? 'Releasing...' : 'Release Seeds'}
			</button>
			<p class="hint">Make seed packs available for download.</p>
		{/if}

		{#if seedsReleased}
			<p class="released-badge">Seeds released ✓</p>
		{/if}

		<button class="btn btn-secondary btn-full" onclick={handleReroll} disabled={loading}>
			{loading ? 'Re-rolling...' : 'Re-roll Seed'}
		</button>
		<p class="hint">
			{seedsReleased
				? 'Assign a different seed. Participants must re-download.'
				: 'Assign a different seed.'}
		</p>
	{:else if raceStatus === 'running'}
		<button class="btn btn-primary btn-full" onclick={handleForceFinish} disabled={loading}>
			{loading ? 'Finishing...' : 'Force Finish'}
		</button>
		<p class="hint">End the race now. Unfinished participants keep their current progress.</p>

		<button class="btn btn-secondary btn-full" onclick={handleReset} disabled={loading}>
			{loading ? 'Resetting...' : 'Reset Race'}
		</button>
		<p class="hint">Clear all progress and return to setup.</p>
	{:else if raceStatus === 'finished'}
		<button class="btn btn-secondary btn-full" onclick={handleReset} disabled={loading}>
			{loading ? 'Resetting...' : 'Reset Race'}
		</button>
		<p class="hint">Clear all progress and return to setup for a re-run.</p>
	{/if}
</div>

{#if pendingConfirm}
	<ConfirmModal
		title={pendingConfirm.title}
		message={pendingConfirm.message}
		confirmLabel={pendingConfirm.confirmLabel}
		danger={pendingConfirm.danger ?? false}
		onConfirm={executeConfirm}
		onCancel={() => (pendingConfirm = null)}
	/>
{/if}

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

	.released-badge {
		color: var(--color-success, #10b981);
		font-size: var(--font-size-sm);
		font-weight: 500;
		margin: 0 0 0.5rem 0;
	}

	.error {
		color: var(--color-danger);
		font-size: var(--font-size-sm);
		margin: 0 0 0.5rem 0;
	}
</style>
