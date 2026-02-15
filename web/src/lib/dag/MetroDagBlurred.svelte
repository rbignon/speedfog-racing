<script lang="ts">
	import { generateFakeDag } from './fakeDag';
	import { computeLayout } from './layout';
	import { EDGE_STROKE_WIDTH } from './constants';
	import type { DagLayout } from './types';

	interface Props {
		totalLayers: number;
		totalNodes: number;
		totalPaths: number;
		transparent?: boolean;
	}

	let { totalLayers, totalNodes, totalPaths, transparent = false }: Props = $props();

	const FAKE_NODE_RADIUS = 6;
	const FAKE_COLOR = '#D4A844';
	const FAKE_EDGE_OPACITY = 0.5;

	let layout: DagLayout = $derived.by(() => {
		const graph = generateFakeDag(totalLayers, totalNodes, totalPaths);
		return computeLayout(graph);
	});
</script>

<div class="blurred-dag-container" class:transparent>
	{#if layout.nodes.length > 0}
		<svg
			viewBox="0 0 {layout.width} {layout.height}"
			width="100%"
			preserveAspectRatio="xMidYMid meet"
			class="blurred-dag-svg"
		>
			{#each layout.edges as edge}
				{#each edge.segments as seg}
					<line
						x1={seg.x1}
						y1={seg.y1}
						x2={seg.x2}
						y2={seg.y2}
						stroke={FAKE_COLOR}
						stroke-width={EDGE_STROKE_WIDTH}
						stroke-linecap="round"
						opacity={FAKE_EDGE_OPACITY}
					/>
				{/each}
			{/each}

			{#each layout.nodes as node}
				<circle cx={node.x} cy={node.y} r={FAKE_NODE_RADIUS} fill={FAKE_COLOR} />
			{/each}
		</svg>
	{/if}
</div>

<style>
	.blurred-dag-container {
		width: 100%;
		overflow: hidden;
		background: var(--color-surface, #1a1a2e);
		border-radius: var(--radius-lg, 8px);
		min-height: 200px;
		display: flex;
		align-items: center;
		justify-content: center;
		filter: blur(8px);
		pointer-events: none;
		opacity: 0.6;
	}

	.blurred-dag-container.transparent {
		background: transparent;
		border-radius: 0;
	}

	.blurred-dag-svg {
		display: block;
		min-width: 600px;
	}
</style>
