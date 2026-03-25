<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { computeHighlights, type Highlight } from '$lib/highlights';
	import { computePersonalHighlights } from '$lib/personal-highlights';
	import { PLAYER_COLORS } from '$lib/dag/constants';

	interface Props {
		participants: WsParticipant[];
		graphJson: Record<string, unknown>;
		myParticipantId?: string;
		onzoneclick?: (nodeId: string) => void;
	}

	let { participants, graphJson, myParticipantId, onzoneclick }: Props = $props();

	let highlights = $derived(computeHighlights(participants, graphJson));
	let personalHighlights = $derived(
		myParticipantId ? computePersonalHighlights(myParticipantId, participants, graphJson) : []
	);

	let showTabs = $derived(!!myParticipantId);
	let activeTab = $state<'race' | 'personal'>('race');
	let displayedHighlights: Highlight[] = $derived(
		activeTab === 'personal' ? personalHighlights : highlights
	);

	function playerColor(playerId: string): string {
		const p = participants.find((pp) => pp.id === playerId);
		return p ? PLAYER_COLORS[p.color_index % PLAYER_COLORS.length] : '#9CA3AF';
	}
</script>

{#if highlights.length > 0 || personalHighlights.length > 0}
	<div class="race-highlights">
		<h2>Highlights</h2>

		{#if showTabs}
			<div class="highlight-tabs">
				<button
					class="tab-btn"
					class:active={activeTab === 'race'}
					onclick={() => (activeTab = 'race')}
				>
					Race
				</button>
				<button
					class="tab-btn"
					class:active={activeTab === 'personal'}
					onclick={() => (activeTab = 'personal')}
				>
					Your Race
				</button>
			</div>
		{/if}

		{#if displayedHighlights.length > 0}
			<ul class="highlight-list">
				{#each displayedHighlights as highlight}
					<li class="highlight-item">
						<span class="highlight-title">{highlight.title}</span>
						<span class="highlight-desc">
							{#each highlight.segments as seg}
								{#if seg.type === 'text'}
									{seg.value}
								{:else if seg.type === 'player'}
									<span class="player-link" style="color: {playerColor(seg.playerId)}"
										>{seg.name}</span
									>
								{:else if seg.type === 'zone'}
									<button class="zone-link" onclick={() => onzoneclick?.(seg.nodeId)}>
										{seg.name}
									</button>
								{/if}
							{/each}
						</span>
					</li>
				{/each}
			</ul>
		{:else if activeTab === 'personal'}
			<p class="no-highlights">No personal highlights for this race.</p>
		{/if}
	</div>
{/if}

<style>
	.race-highlights {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 1.5rem;
	}

	h2 {
		color: var(--color-gold);
		margin: 0 0 1rem 0;
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	.highlight-tabs {
		display: flex;
		gap: 0.25rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 0.25rem;
		width: fit-content;
		margin-bottom: 1rem;
	}

	.tab-btn {
		all: unset;
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
		padding: 0.35rem 0.9rem;
		border-radius: var(--radius-md);
		cursor: pointer;
		transition: all var(--transition);
	}

	.tab-btn:hover {
		color: var(--color-text-secondary);
	}

	.tab-btn.active {
		background: var(--color-border);
		color: var(--color-text);
		font-weight: 600;
	}

	.highlight-list {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.highlight-item {
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		padding: 0.5rem 0;
		border-bottom: 1px solid var(--color-border);
	}

	.highlight-item:last-child {
		border-bottom: none;
		padding-bottom: 0;
	}

	.highlight-title {
		font-weight: 600;
		font-size: var(--font-size-base);
		color: var(--color-text);
	}

	.highlight-desc {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.player-link {
		font-weight: 600;
	}

	.zone-link {
		all: unset;
		color: var(--color-purple);
		cursor: pointer;
		font: inherit;
		text-decoration: underline;
		text-decoration-color: transparent;
		transition: text-decoration-color var(--transition);
	}

	.zone-link:hover {
		text-decoration-color: var(--color-purple);
	}

	.no-highlights {
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
		margin: 0;
	}
</style>
