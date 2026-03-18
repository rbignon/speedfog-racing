<script lang="ts">
	import {
		fetchPlayerProfiles,
		type PlayerProfilesResponse,
		type TraitPlayerEntry
	} from '$lib/api';
	import { SvelteSet } from 'svelte/reactivity';

	interface TraitMeta {
		key: string;
		label: string;
		color: string;
		icon: string;
		description: string;
	}

	const TRAITS: TraitMeta[] = [
		{
			key: 'rusher',
			label: 'Rusher',
			color: '#EF4444',
			icon: '\u26A1',
			description: 'Finishes fast, takes more deaths along the way'
		},
		{
			key: 'cautious',
			label: 'Cautious',
			color: '#10B981',
			icon: '\uD83D\uDEE1',
			description: 'Low deaths relative to time, plays it safe'
		},
		{
			key: 'boss_slayer',
			label: 'Boss Slayer',
			color: '#FBBF24',
			icon: '\u2694',
			description: 'Fewer deaths than average on hard bosses'
		},
		{
			key: 'resilient',
			label: 'Resilient',
			color: '#C8A44E',
			icon: '\uD83D\uDCAA',
			description: 'Keeps finishing despite high death counts'
		},
		{
			key: 'explorer',
			label: 'Explorer',
			color: '#3B82F6',
			icon: '\uD83C\uDF10',
			description: 'Visits many nodes, backtracks often'
		},
		{
			key: 'pathfinder',
			label: 'Pathfinder',
			color: '#A78BFA',
			icon: '\uD83E\uDDED',
			description: 'Takes unique paths others avoid'
		},
		{
			key: 'rage_quitter',
			label: 'Rage Quitter',
			color: '#DC2626',
			icon: '\uD83D\uDCA5',
			description: 'High abandon rate across races'
		}
	];

	let data = $state<PlayerProfilesResponse | null>(null);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let expandedTraits = new SvelteSet<string>();

	$effect(() => {
		loadData();
	});

	async function loadData() {
		loading = true;
		error = null;
		try {
			data = await fetchPlayerProfiles();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load player profiles.';
		} finally {
			loading = false;
		}
	}

	function getPlayers(traitKey: string): TraitPlayerEntry[] {
		return data?.profiles[traitKey] ?? [];
	}

	function visiblePlayers(traitKey: string): TraitPlayerEntry[] {
		const all = getPlayers(traitKey);
		if (expandedTraits.has(traitKey)) return all;
		return all.slice(0, 3);
	}

	function toggleExpand(traitKey: string) {
		if (expandedTraits.has(traitKey)) {
			expandedTraits.delete(traitKey);
		} else {
			expandedTraits.add(traitKey);
		}
	}

	function maxScore(traitKey: string): number {
		const players = getPlayers(traitKey);
		return Math.max(1, ...players.map((p) => p.score));
	}

	let activeSections = $derived(TRAITS.filter((t) => getPlayers(t.key).length > 0));
</script>

{#if loading}
	<p class="loading-text">Loading player profiles...</p>
{:else if error}
	<p class="error-text">{error}</p>
{:else if activeSections.length === 0}
	<p class="empty">No player profiles available yet.</p>
{:else}
	<div class="traits-list">
		{#each activeSections as trait}
			{@const players = getPlayers(trait.key)}
			{@const visible = visiblePlayers(trait.key)}
			{@const max = maxScore(trait.key)}
			<section class="trait-section">
				<div class="trait-header">
					<span class="trait-icon">{trait.icon}</span>
					<span class="trait-name" style="color: {trait.color}">{trait.label}</span>
					<span class="trait-description">{trait.description}</span>
					<span class="trait-count">{players.length}</span>
				</div>

				<div class="trait-players">
					{#each visible as player, i}
						<div class="trait-player-row">
							<span
								class="trait-rank"
								style="color: {i === 0 ? trait.color : 'var(--color-text-secondary)'}"
							>
								#{i + 1}
							</span>
							<div class="trait-player-info">
								{#if player.twitch_avatar_url}
									<img src={player.twitch_avatar_url} alt="" class="trait-player-avatar" />
								{:else}
									<div class="trait-player-avatar-placeholder"></div>
								{/if}
								<a href="/user/{player.twitch_username}" class="trait-player-name">
									{player.twitch_display_name || player.twitch_username}
								</a>
							</div>
							<span class="trait-score">{player.score.toFixed(0)}</span>
							<div class="trait-bar-cell">
								<div
									class="trait-bar"
									style="width: {Math.max(
										4,
										(player.score / max) * 100
									)}%; background: {trait.color}"
								></div>
							</div>
						</div>
					{/each}
				</div>

				{#if players.length > 3}
					<button class="expand-btn" onclick={() => toggleExpand(trait.key)}>
						{expandedTraits.has(trait.key) ? 'Show less' : `Show all (${players.length})`}
					</button>
				{/if}
			</section>
		{/each}
	</div>
{/if}

<style>
	.loading-text,
	.error-text {
		color: var(--color-text-disabled);
		font-style: italic;
		padding: 2rem 0;
	}

	.error-text {
		color: var(--color-danger);
	}

	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
		padding: 2rem 0;
	}

	.traits-list {
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.trait-section {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 1.25rem;
	}

	.trait-header {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 1rem;
		flex-wrap: wrap;
	}

	.trait-icon {
		font-size: 1.1rem;
	}

	.trait-name {
		font-weight: 700;
		font-size: var(--font-size-base);
	}

	.trait-description {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		flex: 1;
	}

	.trait-count {
		font-size: var(--font-size-xs);
		font-weight: 600;
		background: rgba(107, 114, 128, 0.15);
		color: var(--color-text-secondary);
		padding: 0.1rem 0.5rem;
		border-radius: var(--radius-sm);
		font-variant-numeric: tabular-nums;
	}

	.trait-players {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.trait-player-row {
		display: grid;
		grid-template-columns: 2.5rem 1fr 3.5rem minmax(60px, 120px);
		align-items: center;
		gap: 0.5rem;
		padding: 0.35rem 0;
	}

	.trait-rank {
		font-weight: 700;
		font-variant-numeric: tabular-nums;
		font-size: var(--font-size-sm);
	}

	.trait-player-info {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		overflow: hidden;
	}

	.trait-player-avatar {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		object-fit: cover;
		flex-shrink: 0;
	}

	.trait-player-avatar-placeholder {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--color-surface-elevated);
		flex-shrink: 0;
	}

	.trait-player-name {
		color: var(--color-text);
		text-decoration: none;
		font-weight: 500;
		font-size: var(--font-size-sm);
		transition: color var(--transition);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.trait-player-name:hover {
		color: var(--color-purple);
	}

	.trait-score {
		text-align: right;
		font-variant-numeric: tabular-nums;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.trait-bar-cell {
		display: flex;
		align-items: center;
	}

	.trait-bar {
		height: 8px;
		border-radius: 4px;
		transition: width 0.3s ease;
	}

	.expand-btn {
		margin-top: 0.75rem;
		background: none;
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		padding: 0.35rem 0.75rem;
		border-radius: var(--radius-md);
		cursor: pointer;
		transition: all var(--transition);
	}

	.expand-btn:hover {
		border-color: var(--color-purple);
		color: var(--color-purple);
	}

	@media (max-width: 640px) {
		.trait-player-row {
			grid-template-columns: 2rem 1fr 3rem 3rem 60px;
			gap: 0.3rem;
		}

		.trait-header {
			flex-direction: column;
			align-items: flex-start;
			gap: 0.25rem;
		}

		.trait-description {
			flex: none;
		}
	}
</style>
