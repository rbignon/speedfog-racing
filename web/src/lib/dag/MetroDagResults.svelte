<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { parseDagGraph } from './types';
	import { computeLayout } from './layout';
	import { pathToWaypoints } from './animation';
	import type { AnimationWaypoint } from './animation';
	import {
		NODE_RADIUS,
		NODE_COLORS,
		BG_COLOR,
		EDGE_STROKE_WIDTH,
		EDGE_COLOR,
		LABEL_MAX_CHARS,
		LABEL_FONT_SIZE,
		LABEL_COLOR,
		LABEL_OFFSET_Y,
		PLAYER_COLORS,
		RACER_DOT_RADIUS
	} from './constants';
	import type { PositionedNode, DagLayout } from './types';

	interface Props {
		graphJson: Record<string, unknown>;
		participants: WsParticipant[];
	}

	let { graphJson, participants }: Props = $props();

	let layout: DagLayout = $derived.by(() => {
		const graph = parseDagGraph(graphJson);
		return computeLayout(graph);
	});

	// Build node ID lookup
	let nodeMap: Map<string, PositionedNode> = $derived.by(() => {
		const map = new Map<string, PositionedNode>();
		for (const node of layout.nodes) {
			map.set(node.id, node);
		}
		return map;
	});

	// Compute player path polylines from zone_history
	interface PlayerPath {
		id: string;
		color: string;
		displayName: string;
		points: string;
		finalX: number;
		finalY: number;
	}

	let playerPaths: PlayerPath[] = $derived.by(() => {
		const paths: PlayerPath[] = [];

		for (const p of participants) {
			if (!p.zone_history || p.zone_history.length === 0) continue;

			// Extract node_ids and deduplicate consecutive identical ones
			const rawNodeIds = p.zone_history.map((e) => e.node_id);
			const deduped: string[] = [];
			for (const nid of rawNodeIds) {
				if (deduped.length === 0 || deduped[deduped.length - 1] !== nid) {
					// Only include nodes that exist in the graph
					if (nodeMap.has(nid)) {
						deduped.push(nid);
					}
				}
			}

			if (deduped.length === 0) continue;

			const waypoints: AnimationWaypoint[] = pathToWaypoints(deduped, layout);
			if (waypoints.length === 0) continue;

			const pointStr = waypoints.map((w) => `${w.x},${w.y}`).join(' ');
			const last = waypoints[waypoints.length - 1];

			paths.push({
				id: p.id,
				color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
				displayName: p.twitch_display_name || p.twitch_username,
				points: pointStr,
				finalX: last.x,
				finalY: last.y
			});
		}

		return paths;
	});

	// Label placement (same logic as MetroDag/MetroDagLive)
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

<div class="metro-dag-container">
	{#if layout.nodes.length > 0}
		<svg
			viewBox="0 0 {layout.width} {layout.height}"
			width="100%"
			preserveAspectRatio="xMidYMid meet"
			class="metro-dag-svg"
		>
			<defs>
				<filter id="results-player-glow" x="-50%" y="-50%" width="200%" height="200%">
					<feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
					<feMerge>
						<feMergeNode in="blur" />
						<feMergeNode in="SourceGraphic" />
					</feMerge>
				</filter>
			</defs>

			<!-- Base edges (dimmed) -->
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
						opacity="0.25"
					/>
				{/each}
			{/each}

			<!-- Player path polylines -->
			{#each playerPaths as path (path.id)}
				<polyline
					points={path.points}
					fill="none"
					stroke={path.color}
					stroke-width="4"
					stroke-linecap="round"
					stroke-linejoin="round"
					opacity="0.8"
				>
					<title>{path.displayName}</title>
				</polyline>
			{/each}

			<!-- Nodes -->
			{#each layout.nodes as node}
				<g class="dag-node" data-type={node.type}>
					<title>{node.displayName}</title>

					{#if node.type === 'start'}
						<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
						<polygon
							points="{node.x - 3},{node.y - 5} {node.x - 3},{node.y + 5} {node.x + 5},{node.y}"
							fill={BG_COLOR}
						/>
					{:else if node.type === 'final_boss'}
						<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
						<rect x={node.x - 4} y={node.y - 4} width="8" height="8" fill={BG_COLOR} />
					{:else if node.type === 'mini_dungeon'}
						<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
					{:else if node.type === 'boss_arena'}
						<circle
							cx={node.x}
							cy={node.y}
							r={nodeRadius(node)}
							fill={BG_COLOR}
							stroke={nodeColor(node)}
							stroke-width="3"
						/>
					{:else if node.type === 'major_boss'}
						<rect
							x={node.x - nodeRadius(node) * 0.7}
							y={node.y - nodeRadius(node) * 0.7}
							width={nodeRadius(node) * 1.4}
							height={nodeRadius(node) * 1.4}
							fill={nodeColor(node)}
							transform="rotate(45 {node.x} {node.y})"
						/>
					{:else if node.type === 'legacy_dungeon'}
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

			<!-- Final position dots -->
			{#each playerPaths as path (path.id)}
				<circle
					cx={path.finalX}
					cy={path.finalY}
					r={RACER_DOT_RADIUS}
					fill={path.color}
					filter="url(#results-player-glow)"
					class="player-dot"
				>
					<title>{path.displayName}</title>
				</circle>
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
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.metro-dag-svg {
		display: block;
		min-width: 600px;
	}

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
		cursor: default;
	}

	.player-dot {
		pointer-events: auto;
	}
</style>
