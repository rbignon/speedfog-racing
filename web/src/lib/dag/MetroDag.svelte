<script lang="ts">
	import ZoomableSvg from './ZoomableSvg.svelte';
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
		LABEL_OFFSET_Y
	} from './constants';
	import type { PositionedNode, DagLayout } from './types';

	let { graphJson }: { graphJson: Record<string, unknown> } = $props();

	let layout: DagLayout = $derived.by(() => {
		const graph = parseDagGraph(graphJson);
		return computeLayout(graph);
	});

	// Compute which nodes get labels above vs below.
	// Only the topmost node in a multi-node layer gets its label above;
	// all others go below (text flows left, away from outgoing edges).
	let labelAbove: Set<string> = $derived.by(() => {
		const above = new Set<string>();
		const byLayer = new Map<number, PositionedNode[]>();
		for (const node of layout.nodes) {
			const list = byLayer.get(node.layer);
			if (list) list.push(node);
			else byLayer.set(node.layer, [node]);
		}
		for (const nodes of byLayer.values()) {
			if (nodes.length < 2) continue;
			const top = nodes.reduce((a, b) => (a.y < b.y ? a : b));
			above.add(top.id);
		}
		return above;
	});

	function truncateLabel(name: string): string {
		const short = name.includes(' - ') ? name.split(' - ').pop()! : name;
		if (short.length <= LABEL_MAX_CHARS) return short;
		return short.slice(0, LABEL_MAX_CHARS - 1) + '\u2026';
	}

	function nodeRadius(node: PositionedNode): number {
		return NODE_RADIUS[node.type];
	}

	function nodeColor(node: PositionedNode): string {
		return NODE_COLORS[node.type];
	}

	function labelX(node: PositionedNode): number {
		if (labelAbove.has(node.id)) return node.x;
		return node.x - 6;
	}

	function labelY(node: PositionedNode): number {
		const r = nodeRadius(node);
		if (labelAbove.has(node.id)) {
			return node.y - r - 8;
		}
		return node.y + r + LABEL_OFFSET_Y - 6;
	}
</script>

{#if layout.nodes.length > 0}
	<ZoomableSvg width={layout.width} height={layout.height}>
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

					<g class="dag-node-shape">
						{#if node.type === 'start'}
							<!-- Terminus (departure): gold circle + play triangle -->
							<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
							<polygon
								points="{node.x - 3},{node.y - 5} {node.x - 3},{node.y + 5} {node.x + 5},{node.y}"
								fill={BG_COLOR}
							/>
						{:else if node.type === 'final_boss'}
							<!-- Terminus (arrival): gold circle + inner square -->
							<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
							<rect x={node.x - 4} y={node.y - 4} width="8" height="8" fill={BG_COLOR} />
						{:else if node.type === 'mini_dungeon'}
							<!-- Standard station: small filled circle -->
							<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
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
							<circle cx={node.x} cy={node.y} r={nodeRadius(node) * 0.5} fill={nodeColor(node)} />
						{/if}
					</g>

					<!-- Label -->
					<text
						x={labelX(node)}
						y={labelY(node)}
						text-anchor={labelAbove.has(node.id) ? 'start' : 'end'}
						font-size={LABEL_FONT_SIZE}
						fill={LABEL_COLOR}
						class="dag-label"
						transform="rotate(-30, {labelX(node)}, {labelY(node)})"
					>
						{truncateLabel(node.displayName)}
					</text>
				</g>
			{/each}
	</ZoomableSvg>
{/if}

<style>
	.dag-label {
		pointer-events: none;
		user-select: none;
		font-family:
			system-ui,
			-apple-system,
			sans-serif;
		paint-order: stroke;
		stroke: var(--color-surface, #1a1a2e);
		stroke-width: 4px;
		stroke-linejoin: round;
	}

	.dag-node {
		cursor: pointer;
	}

	.dag-node-shape {
		transform-box: fill-box;
		transform-origin: center;
		transition: transform 0.15s ease;
	}

	.dag-node:hover .dag-node-shape {
		transform: scale(1.3);
	}
</style>
