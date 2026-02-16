<script lang="ts">
	import { removeCaster, fetchRace, type Caster, type RaceDetail } from '$lib/api';
	import ParticipantSearch from './ParticipantSearch.svelte';

	interface Props {
		casters: Caster[];
		editable?: boolean;
		raceId?: string;
		onRaceUpdated?: (race: RaceDetail) => void;
	}

	let { casters, editable = false, raceId, onRaceUpdated }: Props = $props();

	let showSearch = $state(false);
	let error = $state<string | null>(null);

	async function handleRemove(caster: Caster) {
		if (!raceId) return;
		error = null;
		try {
			await removeCaster(raceId, caster.id);
			if (raceId && onRaceUpdated) {
				const updated = await fetchRace(raceId);
				onRaceUpdated(updated);
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to remove caster';
		}
	}

	async function handleAdded() {
		showSearch = false;
		if (raceId && onRaceUpdated) {
			const updated = await fetchRace(raceId);
			onRaceUpdated(updated);
		}
	}
</script>

{#if casters.length > 0 || editable}
	<div class="caster-section">
		<h3>
			Casters{#if casters.length > 0}
				({casters.length}){/if}
		</h3>

		{#if error}
			<p class="error">{error}</p>
		{/if}

		{#if casters.length > 0}
			<ul>
				{#each casters as caster (caster.id)}
					<li class="caster-item">
						{#if caster.user.twitch_avatar_url}
							<img src={caster.user.twitch_avatar_url} alt="" class="avatar" />
						{:else}
							<div class="avatar-placeholder"></div>
						{/if}
						<a href="/user/{caster.user.twitch_username}" class="name name-link">
							{caster.user.twitch_display_name || caster.user.twitch_username}
						</a>
						<a
							href="https://twitch.tv/{caster.user.twitch_username}"
							target="_blank"
							rel="noopener noreferrer"
							class="twitch-link"
							title="View on Twitch"
						>
							<svg
								width="14"
								height="14"
								viewBox="0 0 24 24"
								fill="none"
								stroke="currentColor"
								stroke-width="2"
								stroke-linecap="round"
								stroke-linejoin="round"
							>
								<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
								<polyline points="15 3 21 3 21 9" />
								<line x1="10" y1="14" x2="21" y2="3" />
							</svg>
						</a>
						{#if editable}
							<button class="remove-btn" onclick={() => handleRemove(caster)} title="Remove caster">
								&times;
							</button>
						{/if}
					</li>
				{/each}
			</ul>
		{/if}

		{#if editable}
			{#if showSearch}
				<div class="search-row">
					<ParticipantSearch
						mode="caster"
						raceId={raceId ?? ''}
						onAdded={handleAdded}
						onCancel={() => (showSearch = false)}
					/>
				</div>
			{:else}
				<button class="add-btn" onclick={() => (showSearch = true)}>+ Add Caster</button>
			{/if}
		{/if}
	</div>
{/if}

<style>
	.caster-section {
		padding-top: 1rem;
		border-top: 1px solid var(--color-border);
	}

	h3 {
		color: var(--color-text-secondary);
		margin: 0 0 0.5rem 0;
		font-size: var(--font-size-sm);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	ul {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.caster-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.avatar {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.avatar-placeholder {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--color-border);
		flex-shrink: 0;
	}

	.name {
		font-size: var(--font-size-sm);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		flex: 1;
		min-width: 0;
	}

	.name-link {
		color: inherit;
		text-decoration: none;
	}

	.name-link:hover {
		color: var(--color-purple);
		text-decoration: underline;
	}

	.twitch-link {
		color: var(--color-twitch);
		display: flex;
		align-items: center;
		flex-shrink: 0;
	}

	.twitch-link:hover {
		color: var(--color-twitch-hover);
	}

	.remove-btn {
		background: none;
		border: none;
		color: var(--color-text-disabled);
		font-size: 1.2rem;
		cursor: pointer;
		padding: 0 0.25rem;
		line-height: 1;
		flex-shrink: 0;
	}

	.remove-btn:hover {
		color: var(--color-danger);
	}

	.error {
		color: var(--color-danger);
		font-size: var(--font-size-sm);
		margin: 0 0 0.5rem 0;
	}

	.add-btn {
		margin-top: 0.5rem;
		width: 100%;
		padding: 0.5rem;
		border: 2px dashed var(--color-border);
		border-radius: var(--radius-sm);
		background: none;
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		transition: all var(--transition);
	}

	.add-btn:hover {
		border-color: var(--color-purple);
		color: var(--color-purple);
	}

	.search-row {
		margin-top: 0.5rem;
	}
</style>
