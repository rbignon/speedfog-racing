<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { createRace, fetchPoolStats, type PoolStats, type PoolInfo } from '$lib/api';
	import PoolSettingsCard from '$lib/components/PoolSettingsCard.svelte';
	import DateTimePicker from '$lib/components/DateTimePicker.svelte';
	import { formatPoolName } from '$lib/utils/format';

	let name = $state('');
	let scheduledAt = $state('');
	let poolName = $state('standard');
	let organizerParticipates = $state(true);
	let isPublic = $state(true);
	let openRegistration = $state(false);
	let maxParticipants = $state(8);
	let pools: PoolStats = $state({});
	let loading = $state(true);
	let creating = $state(false);
	let error = $state<string | null>(null);
	let authChecked = $state(false);

	let sortedPools = $derived(
		Object.entries(pools)
			.map(([p, info]) => [p, info] as [string, PoolInfo])
			.sort((a, b) => (a[1].pool_config?.sort_order ?? 99) - (b[1].pool_config?.sort_order ?? 99))
	);

	let hasAvailablePool = $derived(sortedPools.some(([, info]) => info.available > 0));
	let selectedConfig = $derived(pools[poolName]?.pool_config ?? null);

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
			error = 'Failed to load seed pools.';
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
				<p class="hint">
					Leave empty if you don't have a fixed start time yet.
				</p>
			</div>

			<div class="form-group">
				<label>Seed Pool</label>
				{#if sortedPools.length === 0}
					<p class="empty-pools">
						No seed pools available. Seeds need to be generated before races can be
						created.
					</p>
				{:else if !hasAvailablePool}
					<div class="pool-cards">
						{#each sortedPools as [pool, info] (pool)}
							<button type="button" class="pool-card disabled">
								<span class="pool-name">{formatPoolName(pool)}</span>
								{#if info.pool_config?.estimated_duration}
									<span class="pool-duration">{info.pool_config?.estimated_duration}</span>
								{/if}
								<span class="pool-seeds">0 seeds available</span>
							</button>
						{/each}
					</div>
					<p class="empty-pools">
						All seed pools are empty. New seeds need to be generated.
					</p>
				{:else}
					<div class="pool-cards">
						{#each sortedPools as [pool, info] (pool)}
							{@const disabled = info.available === 0}
							<button
								type="button"
								class="pool-card"
								class:selected={poolName === pool}
								class:disabled
								onclick={() => { if (!disabled && !creating) poolName = pool; }}
							>
								<span class="pool-name">{formatPoolName(pool)}</span>
								{#if info.pool_config?.estimated_duration}
									<span class="pool-duration">{info.pool_config?.estimated_duration}</span>
								{/if}
								{#if info.pool_config?.description}
									<span class="pool-desc">{info.pool_config?.description}</span>
								{/if}
								<span class="pool-seeds">
									{info.available} seed{info.available !== 1 ? 's' : ''} available
								</span>
							</button>
						{/each}
					</div>
					{#if selectedConfig}
						<PoolSettingsCard poolName={poolName} poolConfig={selectedConfig} compact />
					{/if}
				{/if}
			</div>

			<div class="form-group">
				<label>Will you participate?</label>
				<div class="radio-group">
					<label class="radio-label">
						<input
							type="radio"
							name="participate"
							checked={organizerParticipates}
							onchange={() => (organizerParticipates = true)}
							disabled={creating}
						/>
						Yes, I'll race
					</label>
					<label class="radio-label">
						<input
							type="radio"
							name="participate"
							checked={!organizerParticipates}
							onchange={() => (organizerParticipates = false)}
							disabled={creating}
						/>
						No, organize only
					</label>
				</div>
				<p class="hint">
					If you choose "organize only", you will see the DAG and cannot join as a player
					later.
				</p>
			</div>

			<div class="form-group">
				<label>Visibility</label>
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
					Private races won't appear on the homepage. Players can still join via direct link
					or invite.
				</p>
			</div>

			<div class="form-group">
				<label>Registration</label>
				<div class="radio-group">
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
						Open registration
					</label>
				</div>
				<p class="hint">
					Open registration lets any logged-in player join the race themselves.
				</p>
				{#if openRegistration}
					<div class="max-participants">
						<label for="max-participants">Max participants</label>
						<input
							type="number"
							id="max-participants"
							bind:value={maxParticipants}
							min="2"
							max="100"
							disabled={creating}
						/>
					</div>
				{/if}
			</div>

			<button type="submit" class="btn btn-primary" disabled={creating || !hasAvailablePool}>
				{creating ? 'Creating...' : 'Create Race'}
			</button>
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
		gap: 1.5rem;
	}

	.form-group {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.form-group > label:first-child {
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

	.pool-cards {
		display: flex;
		gap: 0.75rem;
		flex-wrap: wrap;
	}

	.pool-card {
		flex: 1;
		min-width: 140px;
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		padding: 1rem;
		border: 2px solid var(--color-border);
		border-radius: var(--radius-lg);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		cursor: pointer;
		text-align: left;
		transition:
			border-color 0.15s,
			background-color 0.15s;
	}

	.pool-card:hover:not(.disabled) {
		border-color: var(--color-text-secondary);
	}

	.pool-card.selected {
		border-color: var(--color-gold);
		background: var(--color-surface-elevated);
	}

	.pool-card.disabled {
		opacity: 0.4;
		cursor: not-allowed;
	}

	.pool-name {
		font-weight: 600;
		font-size: var(--font-size-lg);
	}

	.pool-duration {
		color: var(--color-gold);
		font-size: var(--font-size-sm);
		font-weight: 500;
	}

	.pool-desc {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		line-height: 1.3;
	}

	.pool-seeds {
		margin-top: 0.25rem;
		color: var(--color-text-disabled);
		font-size: var(--font-size-xs);
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

	.max-participants {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		margin-top: 0.5rem;
	}

	.max-participants label {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		white-space: nowrap;
		font-weight: normal;
		text-transform: none;
		letter-spacing: normal;
	}

	.max-participants input[type='number'] {
		width: 80px;
		padding: 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: 1rem;
	}

	.max-participants input[type='number']:focus {
		outline: none;
		border-color: var(--color-purple);
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

	button[type='submit'] {
		align-self: flex-start;
	}

	@media (max-width: 640px) {
		main {
			padding: 1rem;
		}

		h1 {
			font-size: var(--font-size-xl);
		}
	}
</style>
