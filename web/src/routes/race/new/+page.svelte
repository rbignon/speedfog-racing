<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { createRace, fetchPoolStats, type PoolStats, type PoolInfo } from '$lib/api';
	import PoolSettingsCard from '$lib/components/PoolSettingsCard.svelte';
	import PoolTabs from '$lib/components/PoolTabs.svelte';
	import DateTimePicker from '$lib/components/DateTimePicker.svelte';

	let name = $state('');
	let scheduledAt = $state('');
	let poolName = $state('standard');
	let organizerParticipates = $state(true);
	let isPublic = $state(true);
	let openRegistration = $state(true);
	let maxParticipants = $state(30);
	let lateJoinEnabled = $state(false);
	let autoEndEnabled = $state(false);
	let lateJoinWindowMinutes = $state(30);
	let raceDurationMinutes = $state(120);
	let privateDag = $state(false);
	let showAdvanced = $state(false);
	let pools: PoolStats = $state({});
	let loading = $state(true);
	let creating = $state(false);
	let error = $state<string | null>(null);
	let authChecked = $state(false);

	let sortedPools = $derived(
		Object.entries(pools)
			.map(([p, info]) => [p, info] as [string, PoolInfo])
			.sort(
				(a, b) =>
					(a[1].pool_config?.sort_order ?? 99) - (b[1].pool_config?.sort_order ?? 99) ||
					a[0].localeCompare(b[0])
			)
	);

	let hasAvailablePool = $derived(sortedPools.some(([, info]) => info.available > 0));
	let selectedConfig = $derived(pools[poolName]?.pool_config ?? null);
	let selectedAvailable = $derived(pools[poolName]?.available ?? 0);

	let advancedCount = $derived(
		(autoEndEnabled ? 1 : 0) + (lateJoinEnabled ? 1 : 0) + (privateDag ? 1 : 0)
	);

	$effect(() => {
		if (auth.initialized && !authChecked) {
			authChecked = true;

			if (!auth.isLoggedIn || !auth.canCreateRace) {
				goto('/');
				return;
			}

			loadPools();
		}
	});

	async function loadPools() {
		try {
			pools = await fetchPoolStats();
			// Default to first pool with available seeds
			const available = sortedPools.find(([, info]) => info.available > 0);
			if (available) poolName = available[0];
		} catch (e) {
			console.error('Failed to fetch pools:', e);
			error = 'Failed to load game modes.';
		} finally {
			loading = false;
		}
	}

	async function handleSubmit(e: Event) {
		e.preventDefault();
		if (!name.trim()) {
			error = 'Please enter a race name.';
			return;
		}

		creating = true;
		error = null;

		try {
			const isoScheduled = scheduledAt || null;
			const race = await createRace(
				name.trim(),
				poolName,
				organizerParticipates,
				{},
				isoScheduled,
				isPublic,
				openRegistration,
				openRegistration ? maxParticipants : null,
				lateJoinEnabled ? lateJoinWindowMinutes : null,
				autoEndEnabled ? raceDurationMinutes : null,
				privateDag
			);
			goto(`/race/${race.id}`);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to create race.';
			creating = false;
		}
	}
</script>

<svelte:head>
	<title>Create Race - SpeedFog Racing</title>
</svelte:head>

<main>
	<h1>Create Race</h1>

	{#if loading}
		<p class="loading">Loading...</p>
	{:else}
		<form onsubmit={handleSubmit}>
			{#if error}
				<div class="error">{error}</div>
			{/if}

			<div class="form-group">
				<label for="name">Race Name</label>
				<input
					type="text"
					id="name"
					bind:value={name}
					placeholder="e.g. Sunday Showdown"
					disabled={creating}
					required
				/>
			</div>

			<div class="form-group">
				<label for="scheduled">Scheduled Time <span class="optional">(optional)</span></label>
				<DateTimePicker
					value={scheduledAt}
					onchange={(iso) => (scheduledAt = iso)}
					min={new Date()}
					disabled={creating}
					placeholder="Pick a date"
				/>
				<p class="hint">Indicative only. The organizer starts the race manually at any time.</p>
			</div>

			<div class="form-group">
				<span>Game Mode</span>
				{#if sortedPools.length === 0}
					<p class="empty-pools">
						No game modes available. Seeds need to be generated before races can be created.
					</p>
				{:else}
					<div class="pool-container">
						<PoolTabs
							pools={sortedPools}
							selected={poolName}
							onselect={(p) => {
								if (!creating) poolName = p;
							}}
							disabled={creating}
						/>
						{#if hasAvailablePool && selectedConfig}
							<div class="pool-content">
								<PoolSettingsCard {poolName} poolConfig={selectedConfig} compact />
								<p class="seeds-available">
									{selectedAvailable} seed{selectedAvailable !== 1 ? 's' : ''} available
								</p>
							</div>
						{/if}
					</div>
					{#if !hasAvailablePool}
						<p class="empty-pools">
							No seeds available in any game mode. New seeds need to be generated.
						</p>
					{/if}
				{/if}
			</div>

			<div class="form-group role-visibility-grid">
				<div class="role-col">
					<span>Your role</span>
					<div class="radio-group">
						<label class="radio-label">
							<input
								type="radio"
								name="participate"
								checked={organizerParticipates}
								onchange={() => (organizerParticipates = true)}
								disabled={creating}
							/>
							I'll race
						</label>
						<label class="radio-label">
							<input
								type="radio"
								name="participate"
								checked={!organizerParticipates}
								onchange={() => (organizerParticipates = false)}
								disabled={creating}
							/>
							Organize only
						</label>
					</div>
					<p class="hint">
						If you choose "Organize only", you will see the metro map and cannot join as a player
						later.
					</p>
				</div>

				<div class="visibility-col">
					<span>Visibility</span>
					<div class="radio-group">
						<label class="radio-label">
							<input
								type="radio"
								name="visibility"
								checked={isPublic}
								onchange={() => (isPublic = true)}
								disabled={creating}
							/>
							Public
						</label>
						<label class="radio-label">
							<input
								type="radio"
								name="visibility"
								checked={!isPublic}
								onchange={() => (isPublic = false)}
								disabled={creating}
							/>
							Private
						</label>
					</div>
					<p class="hint">
						Private races don't appear on the homepage and don't count towards rankings. Players can
						still join via direct link or invite.
					</p>
				</div>
			</div>

			<div class="form-group">
				<span>Registration</span>
				<div class="registration-row">
					<label class="radio-label">
						<input
							type="radio"
							name="registration"
							checked={!openRegistration}
							onchange={() => (openRegistration = false)}
							disabled={creating}
						/>
						Invite only
					</label>
					<label class="radio-label">
						<input
							type="radio"
							name="registration"
							checked={openRegistration}
							onchange={() => (openRegistration = true)}
							disabled={creating}
						/>
						Open
					</label>
					{#if openRegistration}
						<span class="registration-sep">·</span>
						<label class="inline-max">
							max
							<input
								type="number"
								bind:value={maxParticipants}
								min="2"
								max="100"
								disabled={creating}
							/>
						</label>
					{/if}
				</div>
				<p class="hint">Open registration lets any logged-in player join the race themselves.</p>
			</div>

			<div class="advanced">
				<button
					type="button"
					class="advanced-trigger"
					onclick={() => (showAdvanced = !showAdvanced)}
					disabled={creating}
					aria-expanded={showAdvanced}
					aria-controls="advanced-panel"
				>
					<span class="advanced-chevron">{showAdvanced ? '▼' : '▸'}</span>
					<span class="advanced-label">Advanced options</span>
					<span class="advanced-summary">
						{#if advancedCount > 0}
							{advancedCount} set
						{:else}
							late joiners · auto-end · private map
						{/if}
					</span>
				</button>

				{#if showAdvanced}
					<div id="advanced-panel" class="advanced-panel">
						<div class="form-group">
							<span>Late joiners</span>
							<label class="radio-label">
								<input type="checkbox" bind:checked={lateJoinEnabled} disabled={creating} />
								Allow joining up to
								{#if lateJoinEnabled}
									<input
										type="number"
										bind:value={lateJoinWindowMinutes}
										min="1"
										max={autoEndEnabled ? raceDurationMinutes : undefined}
										disabled={creating}
										class="inline-duration"
									/>
									min after start
								{/if}
							</label>
							<p class="hint">Counted from the actual start time.</p>
						</div>

						<div class="form-group">
							<span>Auto-end</span>
							<label class="radio-label">
								<input type="checkbox" bind:checked={autoEndEnabled} disabled={creating} />
								End race automatically after
								{#if autoEndEnabled}
									<input
										type="number"
										bind:value={raceDurationMinutes}
										min="1"
										disabled={creating}
										class="inline-duration"
									/>
									min
								{/if}
							</label>
							<p class="hint">
								Useful for time-boxed community races. The organizer can still finalize earlier.
							</p>
						</div>

						<div class="form-group">
							<span>Spoiler protection</span>
							<label class="radio-label">
								<input type="checkbox" bind:checked={privateDag} disabled={creating} />
								Hide the map from non-participants until the race finishes
							</label>
							<p class="hint">Useful for asynchronous races where spoilers matter.</p>
						</div>
					</div>
				{/if}
			</div>

			<div class="actions">
				<button type="submit" class="btn btn-primary" disabled={creating || !hasAvailablePool}>
					{creating ? 'Creating...' : 'Create Race'}
				</button>
				<button
					type="button"
					class="btn btn-secondary"
					onclick={() => goto('/races')}
					disabled={creating}
				>
					Cancel
				</button>
			</div>
		</form>
	{/if}
</main>

<style>
	main {
		max-width: 600px;
		margin: 0 auto;
		padding: 2rem;
	}

	h1 {
		color: var(--color-text);
		font-size: var(--font-size-2xl);
		font-weight: 600;
		margin-bottom: 2rem;
	}

	form {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.form-group > :is(label, span):first-child {
		font-weight: 500;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	input[type='text'] {
		padding: 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: 1rem;
	}

	input[type='text']:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	input[type='text']:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.optional {
		font-weight: 400;
		text-transform: none;
		letter-spacing: normal;
		color: var(--color-text-disabled);
	}

	.pool-container {
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
	}

	.pool-content {
		padding: 1rem;
		background: var(--color-surface-elevated);
	}

	.pool-content > :global(.card) {
		background: transparent;
		border-radius: 0;
		padding: 0;
	}

	.seeds-available {
		margin: 0.75rem 0 0;
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
	}

	.radio-group {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.radio-label {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		cursor: pointer;
		font-size: 1rem;
		font-weight: normal;
		color: var(--color-text);
		text-transform: none;
		letter-spacing: normal;
	}

	.empty-pools {
		color: var(--color-text-disabled);
		font-style: italic;
		margin: 0;
		padding: 1rem;
		background: var(--color-surface);
		border-radius: var(--radius-sm);
		border: 1px dashed var(--color-border);
	}

	.hint {
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
		margin: 0;
		line-height: 1.4;
	}

	.role-visibility-grid {
		display: grid;
		grid-template-columns: 1fr 1fr;
		gap: 1.25rem;
	}

	.role-col,
	.visibility-col {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.role-col > span:first-child,
	.visibility-col > span:first-child {
		font-weight: 500;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.registration-row {
		display: flex;
		flex-wrap: wrap;
		align-items: center;
		gap: 0.75rem;
	}

	.registration-sep {
		color: var(--color-text-disabled);
	}

	.inline-max {
		display: inline-flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 1rem;
		font-weight: normal;
		color: var(--color-text);
	}

	.inline-max input[type='number'] {
		width: 70px;
		padding: 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: 1rem;
	}

	.inline-max input[type='number']:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	.actions {
		display: flex;
		gap: 0.75rem;
		align-self: flex-start;
	}

	.inline-duration {
		width: 70px;
		padding: 0.35rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: 1rem;
		margin: 0 0.25rem;
	}

	.inline-duration:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	.advanced {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.advanced-trigger {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 1rem;
		background: transparent;
		border: 1px dashed var(--color-border);
		border-radius: var(--radius-sm);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		text-align: left;
		cursor: pointer;
	}

	.advanced-trigger:hover:not(:disabled) {
		border-color: var(--color-purple);
	}

	.advanced-trigger:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.advanced-chevron {
		color: var(--color-purple);
	}

	.advanced-label {
		font-weight: 500;
	}

	.advanced-summary {
		margin-left: auto;
		color: var(--color-text-disabled);
	}

	.advanced-panel {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
		padding-left: 1rem;
		border-left: 2px solid rgba(139, 92, 246, 0.3);
	}

	.error {
		background: var(--color-danger-dark);
		color: white;
		padding: 0.75rem;
		border-radius: var(--radius-sm);
	}

	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	@media (max-width: 640px) {
		main {
			padding: 1rem;
		}

		h1 {
			font-size: var(--font-size-xl);
		}

		.role-visibility-grid {
			grid-template-columns: 1fr;
		}
	}
</style>
