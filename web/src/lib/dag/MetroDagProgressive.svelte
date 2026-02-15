<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { parseDagGraph } from './types';
	import { computeLayout } from './layout';
	import {
		computeNodeVisibility,
		filterVisibleNodes,
		filterVisibleEdges,
		edgeOpacity,
		extractDiscoveredIds
	} from './visibility';
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
		PLAYER_COLORS,
		RACER_DOT_RADIUS,
		ADJACENT_NODE_COLOR,
		ADJACENT_OPACITY,
		REVEAL_TRANSITION_MS
	} from './constants';
	import type { PositionedNode, DagLayout } from './types';
	import type { NodeVisibility } from './visibility';

	interface Props {
		graphJson: Record<string, unknown>;
		participants: WsParticipant[];
		myParticipantId: string;
	}

	let { graphJson, participants, myParticipantId }: Props = $props();

	// Full layout (stable positions regardless of visibility)
	let layout: DagLayout = $derived.by(() => {
		const graph = parseDagGraph(graphJson);
		return computeLayout(graph);
	});

	// Parse graph for edges (needed for adjacency computation)
	let graph = $derived(parseDagGraph(graphJson));

	// Extract discovered node IDs from my participant's zone_history
	let discoveredIds: Set<string> = $derived.by(() => {
		const me = participants.find((p) => p.id === myParticipantId);
		if (!me) return new Set<string>();
		return extractDiscoveredIds(me.zone_history, me.current_zone);
	});

	// Compute visibility for all nodes
	let visibility: Map<string, NodeVisibility> = $derived.by(() => {
		return computeNodeVisibility(graph.nodes, graph.edges, discoveredIds);
	});

	// Visible nodes and edges
	let visibleNodes: PositionedNode[] = $derived(filterVisibleNodes(layout.nodes, visibility));
	let visibleEdges = $derived(filterVisibleEdges(layout.edges, visibility));

	// Node ID lookup for player dot positioning
	let nodeById = $derived.by(() => {
		const map = new Map<string, PositionedNode>();
		for (const node of layout.nodes) {
			map.set(node.id, node);
		}
		return map;
	});

	// Player dot (only for my participant, only on discovered nodes)
	let playerDot = $derived.by(() => {
		const me = participants.find((p) => p.id === myParticipantId);
		if (!me || !me.current_zone) return null;
		if (me.status !== 'playing' && me.status !== 'finished') return null;
		if (visibility.get(me.current_zone) !== 'discovered') return null;

		const node = nodeById.get(me.current_zone);
		if (!node) return null;

		return {
			x: node.x,
			y: node.y,
			color: PLAYER_COLORS[me.color_index % PLAYER_COLORS.length],
			displayName: me.twitch_display_name || me.twitch_username
		};
	});

	// Label placement (same logic as MetroDagLive)
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
		const vis = visibility.get(node.id);
		return vis === 'discovered' ? NODE_COLORS[node.type] : ADJACENT_NODE_COLOR;
	}

	function nodeOpacity(node: PositionedNode): number {
		return visibility.get(node.id) === 'discovered' ? 1.0 : ADJACENT_OPACITY;
	}

	function isDiscovered(node: PositionedNode): boolean {
		return visibility.get(node.id) === 'discovered';
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

	let transitionStyle = `transition: opacity ${REVEAL_TRANSITION_MS}ms ease`;
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
				<filter id="player-glow-prog" x="-50%" y="-50%" width="200%" height="200%">
					<feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
					<feMerge>
						<feMergeNode in="blur" />
						<feMergeNode in="SourceGraphic" />
					</feMerge>
				</filter>
			</defs>

			<!-- Edges -->
			{#each visibleEdges as edge (edge.fromId + '-' + edge.toId)}
				<g style={transitionStyle} opacity={edgeOpacity(edge, visibility, EDGE_OPACITY)}>
					{#each edge.segments as seg}
						<line
							x1={seg.x1}
							y1={seg.y1}
							x2={seg.x2}
							y2={seg.y2}
							stroke={EDGE_COLOR}
							stroke-width={EDGE_STROKE_WIDTH}
							stroke-linecap="round"
						/>
					{/each}
				</g>
			{/each}

			<!-- Nodes -->
			{#each visibleNodes as node (node.id)}
				<g
					class="dag-node"
					data-type={node.type}
					style={transitionStyle}
					opacity={nodeOpacity(node)}
				>
					<title>{isDiscovered(node) ? node.displayName : '???'}</title>

					<g class="dag-node-shape">
						{#if node.type === 'start'}
							<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
							{#if isDiscovered(node)}
								<polygon
									points="{node.x - 3},{node.y - 5} {node.x - 3},{node.y + 5} {node.x + 5},{node.y}"
									fill={BG_COLOR}
								/>
							{/if}
						{:else if node.type === 'final_boss'}
							<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
							{#if isDiscovered(node)}
								<rect x={node.x - 4} y={node.y - 4} width="8" height="8" fill={BG_COLOR} />
							{/if}
						{:else if node.type === 'mini_dungeon'}
							<circle cx={node.x} cy={node.y} r={nodeRadius(node)} fill={nodeColor(node)} />
						{:else if node.type === 'boss_arena'}
							{#if isDiscovered(node)}
								<circle
									cx={node.x}
									cy={node.y}
									r={nodeRadius(node)}
									fill={BG_COLOR}
									stroke={nodeColor(node)}
									stroke-width="3"
								/>
							{:else}
								<circle
									cx={node.x}
									cy={node.y}
									r={nodeRadius(node)}
									fill={nodeColor(node)}
								/>
							{/if}
						{:else if node.type === 'major_boss'}
							{#if isDiscovered(node)}
								<rect
									x={node.x - nodeRadius(node) * 0.7}
									y={node.y - nodeRadius(node) * 0.7}
									width={nodeRadius(node) * 1.4}
									height={nodeRadius(node) * 1.4}
									fill={nodeColor(node)}
									transform="rotate(45 {node.x} {node.y})"
								/>
							{:else}
								<circle
									cx={node.x}
									cy={node.y}
									r={nodeRadius(node)}
									fill={nodeColor(node)}
								/>
							{/if}
						{:else if node.type === 'legacy_dungeon'}
							{#if isDiscovered(node)}
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
							{:else}
								<circle
									cx={node.x}
									cy={node.y}
									r={nodeRadius(node)}
									fill={nodeColor(node)}
								/>
							{/if}
						{/if}
					</g>

					<!-- Label (only for discovered nodes) -->
					{#if isDiscovered(node)}
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
					{/if}
				</g>
			{/each}

			<!-- Player dot -->
			{#if playerDot}
				<circle
					cx={playerDot.x}
					cy={playerDot.y}
					r={RACER_DOT_RADIUS}
					fill={playerDot.color}
					filter="url(#player-glow-prog)"
					class="player-dot"
				>
					<title>{playerDot.displayName}</title>
				</circle>
			{/if}
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

	.player-dot {
		transition:
			cx 0.3s ease,
			cy 0.3s ease;
	}
</style>
