<script lang="ts">
	import { parseDagGraph } from './types';
	import { computeLayout } from './layout';
	import {
		NODE_RADIUS,
		NODE_COLORS,
		BG_COLOR,
		EDGE_STROKE_WIDTH,
		EDGE_COLOR,
		EDGE_OPACITY,
		LABEL_MAX_CHARS,
		LABEL_FONT_SIZE,
		LABEL_COLOR,
		LABEL_OFFSET_Y,
	} from './constants';
	import type { PositionedNode, DagLayout } from './types';

	let { graphJson }: { graphJson: Record<string, unknown> } = $props();

	let layout: DagLayout = $derived.by(() => {
		const graph = parseDagGraph(graphJson);
		return computeLayout(graph);
	});

	function truncateLabel(name: string): string {
		if (name.length <= LABEL_MAX_CHARS) return name;
		return name.slice(0, LABEL_MAX_CHARS - 1) + '\u2026';
	}

	function nodeRadius(node: PositionedNode): number {
		return NODE_RADIUS[node.type];
	}

	function nodeColor(node: PositionedNode): string {
		return NODE_COLORS[node.type];
	}
</script>

<div class="metro-dag-container">
	{#if layout.nodes.length > 0}
		<svg
			viewBox="0 0 {layout.width} {layout.height}"
			width="100%"
			preserveAspectRatio="xMidYMid meet"
			class="metro-dag-svg"
		>
			<!-- Edges (rendered first, behind nodes) -->
			{#each layout.edges as edge}
				{#each edge.segments as seg}
					<line
						x1={seg.x1}
						y1={seg.y1}
						x2={seg.x2}
						y2={seg.y2}
						stroke={EDGE_COLOR}
						stroke-width={EDGE_STROKE_WIDTH}
						stroke-linecap="round"
						opacity={EDGE_OPACITY}
					/>
				{/each}
			{/each}

			<!-- Nodes -->
			{#each layout.nodes as node}
				<g class="dag-node" data-type={node.type}>
					<title>{node.displayName}</title>

					{#if node.type === 'start'}
						<!-- Terminus (departure): gold circle + play triangle -->
						<circle
							cx={node.x}
							cy={node.y}
							r={nodeRadius(node)}
							fill={nodeColor(node)}
						/>
						<polygon
							points="{node.x - 3},{node.y - 5} {node.x - 3},{node.y + 5} {node.x + 5},{node.y}"
							fill={BG_COLOR}
						/>
					{:else if node.type === 'final_boss'}
						<!-- Terminus (arrival): gold circle + inner square -->
						<circle
							cx={node.x}
							cy={node.y}
							r={nodeRadius(node)}
							fill={nodeColor(node)}
						/>
						<rect
							x={node.x - 4}
							y={node.y - 4}
							width="8"
							height="8"
							fill={BG_COLOR}
						/>
					{:else if node.type === 'mini_dungeon'}
						<!-- Standard station: small filled circle -->
						<circle
							cx={node.x}
							cy={node.y}
							r={nodeRadius(node)}
							fill={nodeColor(node)}
						/>
					{:else if node.type === 'boss_arena'}
						<!-- Interchange: circle with thick stroke border -->
						<circle
							cx={node.x}
							cy={node.y}
							r={nodeRadius(node)}
							fill={BG_COLOR}
							stroke={nodeColor(node)}
							stroke-width="3"
						/>
					{:else if node.type === 'major_boss'}
						<!-- Zone station: rotated diamond -->
						<rect
							x={node.x - nodeRadius(node) * 0.7}
							y={node.y - nodeRadius(node) * 0.7}
							width={nodeRadius(node) * 1.4}
							height={nodeRadius(node) * 1.4}
							fill={nodeColor(node)}
							transform="rotate(45 {node.x} {node.y})"
						/>
					{:else if node.type === 'legacy_dungeon'}
						<!-- Major station (RER): double concentric circles -->
						<circle
							cx={node.x}
							cy={node.y}
							r={nodeRadius(node)}
							fill="none"
							stroke={nodeColor(node)}
							stroke-width="3"
						/>
						<circle
							cx={node.x}
							cy={node.y}
							r={nodeRadius(node) * 0.5}
							fill={nodeColor(node)}
						/>
					{/if}

					<!-- Label -->
					<text
						x={node.x}
						y={node.y + nodeRadius(node) + LABEL_OFFSET_Y}
						text-anchor="middle"
						font-size={LABEL_FONT_SIZE}
						fill={LABEL_COLOR}
						class="dag-label"
					>
						{truncateLabel(node.displayName)}
					</text>
				</g>
			{/each}
		</svg>
	{/if}
</div>

<style>
	.metro-dag-container {
		width: 100%;
		overflow-x: auto;
		background: var(--color-surface, #1a1a2e);
		border-radius: var(--radius-lg, 8px);
		min-height: 200px;
	}

	.metro-dag-svg {
		display: block;
		min-width: 600px;
	}

	.dag-label {
		pointer-events: none;
		user-select: none;
		font-family: system-ui, -apple-system, sans-serif;
	}

	.dag-node {
		cursor: default;
	}
</style>
