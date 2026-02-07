<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
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

	// Build zone-to-node lookup: maps a zone name to its positioned node
	let zoneToNode: Map<string, PositionedNode> = $derived.by(() => {
		const map = new Map<string, PositionedNode>();
		for (const node of layout.nodes) {
			for (const zone of node.zones) {
				map.set(zone, node);
			}
		}
		return map;
	});

	// Compute player dot positions with stacking offsets for same-node collisions
	let playerDots: {
		id: string;
		x: number;
		y: number;
		color: string;
		displayName: string;
	}[] = $derived.by(() => {
		const dots: {
			id: string;
			x: number;
			y: number;
			color: string;
			displayName: string;
		}[] = [];

		// Group active participants by their node
		const nodeGroups = new Map<string, { participant: WsParticipant; node: PositionedNode }[]>();

		for (const p of participants) {
			if (p.status !== 'playing' && p.status !== 'finished') continue;
			if (!p.current_zone) continue;

			const node = zoneToNode.get(p.current_zone);
			if (!node) continue;

			const group = nodeGroups.get(node.id);
			if (group) {
				group.push({ participant: p, node });
			} else {
				nodeGroups.set(node.id, [{ participant: p, node }]);
			}
		}

		// Position dots with vertical offset for stacking
		const DOT_STACK_OFFSET = RACER_DOT_RADIUS * 2.5;

		for (const group of nodeGroups.values()) {
			const totalOffset = (group.length - 1) * DOT_STACK_OFFSET;
			const startY = -totalOffset / 2;

			for (let i = 0; i < group.length; i++) {
				const { participant, node } = group[i];
				dots.push({
					id: participant.id,
					x: node.x,
					y: node.y + startY + i * DOT_STACK_OFFSET,
					color: PLAYER_COLORS[participant.color_index % PLAYER_COLORS.length],
					displayName: participant.twitch_display_name || participant.twitch_username
				});
			}
		}

		return dots;
	});

	// Label placement (same logic as MetroDag)
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
				<filter id="player-glow" x="-50%" y="-50%" width="200%" height="200%">
					<feGaussianBlur in="SourceGraphic" stdDeviation="3" result="blur" />
					<feMerge>
						<feMergeNode in="blur" />
						<feMergeNode in="SourceGraphic" />
					</feMerge>
				</filter>
			</defs>

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

			<!-- Player dots (rendered on top of everything) -->
			{#each playerDots as dot (dot.id)}
				<circle
					cx={dot.x}
					cy={dot.y}
					r={RACER_DOT_RADIUS}
					fill={dot.color}
					filter="url(#player-glow)"
					class="player-dot"
				>
					<title>{dot.displayName}</title>
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
