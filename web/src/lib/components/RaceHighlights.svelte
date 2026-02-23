<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { computeHighlights } from '$lib/highlights';

	interface Props {
		participants: WsParticipant[];
		graphJson: Record<string, unknown>;
	}

	let { participants, graphJson }: Props = $props();

	let highlights = $derived(computeHighlights(participants, graphJson));
</script>

{#if highlights.length > 0}
	<div class="race-highlights">
		<h2>Highlights</h2>
		<ul class="highlight-list">
			{#each highlights as highlight}
				<li class="highlight-item">
					<span class="highlight-title">{highlight.title}</span>
					<span class="highlight-desc">{highlight.description}</span>
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
</style>
