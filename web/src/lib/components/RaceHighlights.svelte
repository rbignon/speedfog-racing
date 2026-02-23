<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { computeHighlights, type DescriptionSegment } from '$lib/highlights';
	import { PLAYER_COLORS } from '$lib/dag/constants';

	interface Props {
		participants: WsParticipant[];
		graphJson: Record<string, unknown>;
		onzoneclick?: (nodeId: string) => void;
	}

	let { participants, graphJson, onzoneclick }: Props = $props();

	let highlights = $derived(computeHighlights(participants, graphJson));

	function playerColor(playerId: string): string {
		const p = participants.find((pp) => pp.id === playerId);
		return p ? PLAYER_COLORS[p.color_index % PLAYER_COLORS.length] : '#9CA3AF';
	}
</script>

{#if highlights.length > 0}
	<div class="race-highlights">
		<h2>Highlights</h2>
		<ul class="highlight-list">
			{#each highlights as highlight}
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
								<button
									class="zone-link"
									onclick={() => onzoneclick?.(seg.nodeId)}
								>
									{seg.name}
								</button>
							{/if}
						{/each}
					</span>
				</li>
			{/each}
		</ul>
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
</style>
