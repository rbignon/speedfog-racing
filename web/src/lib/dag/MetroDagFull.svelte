<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import ZoomableSvg from './ZoomableSvg.svelte';
	import FollowViewport from './FollowViewport.svelte';
	import LivePlayerDots from './LivePlayerDots.svelte';
	import { parseDagGraph } from './types';
	import { computeLayout } from './layout';
	import { expandNodePath, buildPlayerWaypoints, computeSlot, canonicalEdgeKey } from './parallel';
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
		RACER_DOT_RADIUS,
		PARALLEL_PATH_SPACING,
		MAX_PARALLEL
	} from './constants';
	import type { DagNode, PositionedNode, RoutedEdge, DagLayout } from './types';
	import NodePopup from './NodePopup.svelte';
	import {
		computeConnections,
		computePlayersAtNode,
		computeVisitors,
		parseExitTexts,
		parseEntranceTexts,
		parseNodeLayers
	} from './popupData';
	import type { NodePopupData } from './popupData';

	interface Props {
		graphJson: Record<string, unknown>;
		participants: WsParticipant[];
		raceStatus?: string;
		transparent?: boolean;
		highlightIds?: Set<string>;
		focusNodeId?: string | null;
		hideLabels?: boolean;
		showLiveDots?: boolean;
		follow?: boolean;
	}

	let {
		graphJson,
		participants,
		raceStatus,
		transparent = false,
		highlightIds,
		focusNodeId = null,
		hideLabels = false,
		showLiveDots = false,
		follow = false
	}: Props = $props();

	let hasHighlight = $derived(highlightIds != null && highlightIds.size > 0);

	let graph = $derived(parseDagGraph(graphJson));

	let layout: DagLayout = $derived.by(() => {
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

	// Build edge lookup: "fromId->toId" -> RoutedEdge
	let edgeMap: Map<string, RoutedEdge> = $derived.by(() => {
		const map = new Map<string, RoutedEdge>();
		for (const edge of layout.edges) {
			map.set(`${edge.fromId}->${edge.toId}`, edge);
		}
		return map;
	});

	// Build bidirectional adjacency list for BFS gap-filling.
	// Players can backtrack through fog gates, so BFS needs reverse edges.
	let adjacency: Map<string, string[]> = $derived.by(() => {
		const adj = new Map<string, string[]>();
		for (const edge of layout.edges) {
			// Forward
			const fwd = adj.get(edge.fromId);
			if (fwd) fwd.push(edge.toId);
			else adj.set(edge.fromId, [edge.toId]);
			// Reverse (backtracking)
			const rev = adj.get(edge.toId);
			if (rev) rev.push(edge.fromId);
			else adj.set(edge.toId, [edge.fromId]);
		}
		return adj;
	});

	// Compute player path polylines with parallel offset on shared edges
	interface PlayerPath {
		id: string;
		color: string;
		displayName: string;
		points: string;
		finalNodeId: string;
		finalX: number;
		finalY: number;
	}

	let playerPaths: PlayerPath[] = $derived.by(() => {
		// Step 1: Deduplicate and expand node paths for each participant
		const expandedMap = new Map<string, string[]>();

		for (const p of participants) {
			if (!p.zone_history || p.zone_history.length === 0) continue;

			const rawNodeIds = p.zone_history.map((e: { node_id: string }) => e.node_id);
			const deduped: string[] = [];
			for (const nid of rawNodeIds) {
				if (deduped.length === 0 || deduped[deduped.length - 1] !== nid) {
					if (nodeMap.has(nid)) {
						deduped.push(nid);
					}
				}
			}

			if (deduped.length === 0) continue;
			expandedMap.set(p.id, expandNodePath(deduped, edgeMap, adjacency));
		}

		// Step 2: Build edge usage map — which participants traverse each edge
		// Uses canonical keys so forward and reverse traversals share one slot pool
		const edgeUsageSets = new Map<string, Set<string>>();
		for (const [participantId, expanded] of expandedMap) {
			for (let i = 0; i < expanded.length - 1; i++) {
				const key = canonicalEdgeKey(expanded[i], expanded[i + 1], edgeMap);
				let s = edgeUsageSets.get(key);
				if (!s) {
					s = new Set<string>();
					edgeUsageSets.set(key, s);
				}
				s.add(participantId);
			}
		}
		const edgeUsage = new Map<string, string[]>();
		for (const [key, s] of edgeUsageSets) {
			edgeUsage.set(key, [...s]);
		}

		// Step 3: Build slot map — for each participant+edge, their centered slot
		// 1 player: 0, 2 players: -0.5/+0.5, 3 players: -1/0/+1, etc.
		const playerSlots = new Map<string, Map<string, number>>();
		for (const [edgeKey, pids] of edgeUsage) {
			const count = Math.min(pids.length, MAX_PARALLEL);
			for (let idx = 0; idx < pids.length; idx++) {
				const slot = idx < MAX_PARALLEL ? computeSlot(idx, count) : 0;
				let pMap = playerSlots.get(pids[idx]);
				if (!pMap) {
					pMap = new Map<string, number>();
					playerSlots.set(pids[idx], pMap);
				}
				pMap.set(edgeKey, slot);
			}
		}

		// Step 4: Build offset waypoints for each player
		const paths: PlayerPath[] = [];

		for (const p of participants) {
			const expanded = expandedMap.get(p.id);
			if (!expanded) continue;

			const pSlots = playerSlots.get(p.id);
			const points = buildPlayerWaypoints(
				expanded,
				nodeMap,
				edgeMap,
				(key) => pSlots?.get(key) ?? 0,
				(key) => edgeUsage.get(key)?.length ?? 1,
				PARALLEL_PATH_SPACING
			);

			if (points.length === 0) continue;

			const pointStr = points.map((w) => `${w.x},${w.y}`).join(' ');
			const last = points[points.length - 1];

			paths.push({
				id: p.id,
				color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
				displayName: p.twitch_display_name || p.twitch_username,
				points: pointStr,
				finalNodeId: expanded[expanded.length - 1],
				finalX: last.x,
				finalY: last.y
			});
		}

		return paths;
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

	// Compute which nodes had deaths, respecting player selection
	let nodesWithDeaths: Set<string> = $derived.by(() => {
		const result = new Set<string>();
		for (const p of participants) {
			if (!p.zone_history) continue;
			// If players are selected, only count their deaths
			if (hasHighlight && !highlightIds!.has(p.id)) continue;
			for (const entry of p.zone_history) {
				if (entry.deaths && entry.deaths > 0) {
					result.add(entry.node_id);
				}
			}
		}
		return result;
	});

	let exitTexts = $derived(parseExitTexts(graphJson));
	let entranceTexts = $derived(parseEntranceTexts(graphJson));
	let nodeLayers = $derived(parseNodeLayers(graphJson));
	let raceFinished = $derived(raceStatus === 'finished');

	// Popup state
	let popupData: NodePopupData | null = $state(null);
	let popupX = $state(0);
	let popupY = $state(0);

	function onNodeClick(nodeId: string, event: PointerEvent) {
		const node = nodeMap.get(nodeId);
		if (!node) return;

		const { entrances, exits } = computeConnections(
			nodeId,
			graph.edges,
			nodeMap as Map<string, DagNode>,
			undefined,
			exitTexts,
			entranceTexts
		);
		const playersHere = computePlayersAtNode(nodeId, participants);
		const visitors = computeVisitors(nodeId, participants, nodeLayers);

		popupData = {
			nodeId,
			displayName: node.displayName,
			type: node.type,
			displayType: node.displayType,
			tier: node.tier,
			randomizedBoss: node.randomizedBoss,
			entrances,
			exits,
			playersHere: raceFinished ? undefined : playersHere,
			visitors,
			raceFinished
		};
		popupX = event.clientX;
		popupY = event.clientY;
	}

	function closePopup() {
		popupData = null;
	}

	let dagContainer: HTMLElement | undefined = $state();

	function openPopupForNode(nodeId: string) {
		const node = nodeMap.get(nodeId);
		if (!node) return;

		const { entrances, exits } = computeConnections(
			nodeId,
			graph.edges,
			nodeMap as Map<string, DagNode>,
			undefined,
			exitTexts,
			entranceTexts
		);
		const playersHere = computePlayersAtNode(nodeId, participants);
		const visitors = computeVisitors(nodeId, participants, nodeLayers);

		popupData = {
			nodeId,
			displayName: node.displayName,
			type: node.type,
			displayType: node.displayType,
			tier: node.tier,
			randomizedBoss: node.randomizedBoss,
			entrances,
			exits,
			playersHere: raceFinished ? undefined : playersHere,
			visitors,
			raceFinished
		};

		// Position popup near the SVG node element
		if (dagContainer) {
			const el = dagContainer.querySelector(`[data-node-id="${CSS.escape(nodeId)}"]`);
			if (el) {
				const rect = el.getBoundingClientRect();
				popupX = rect.left + rect.width / 2;
				popupY = rect.top;
				return;
			}
		}
		// Fallback: center of container
		if (dagContainer) {
			const rect = dagContainer.getBoundingClientRect();
			popupX = rect.left + rect.width / 2;
			popupY = rect.top + rect.height / 2;
		}
	}

	$effect(() => {
		if (focusNodeId) {
			openPopupForNode(focusNodeId);
		}
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

	// Trailing path segments for follow mode
	interface TrailingSegment {
		key: string;
		x1: number;
		y1: number;
		x2: number;
		y2: number;
		color: string;
		opacity: number;
	}

	let trailingPaths: TrailingSegment[] = $derived.by(() => {
		if (!follow) return [];
		const TRAIL_LENGTH = 3;
		const OPACITY_LEVELS = [0.8, 0.4, 0.15];
		const result: TrailingSegment[] = [];

		for (const p of participants) {
			if (!p.zone_history || p.zone_history.length < 2) continue;
			const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];

			// Take last TRAIL_LENGTH+1 zone entries to get TRAIL_LENGTH edges
			const recent = p.zone_history.slice(-TRAIL_LENGTH - 1);
			const edges: { from: string; to: string }[] = [];
			for (let i = 0; i < recent.length - 1; i++) {
				if (recent[i].node_id !== recent[i + 1].node_id) {
					edges.push({ from: recent[i].node_id, to: recent[i + 1].node_id });
				}
			}

			// Render most recent first
			for (let i = edges.length - 1; i >= 0; i--) {
				const age = edges.length - 1 - i;
				if (age >= TRAIL_LENGTH) break;
				const fromNode = nodeMap.get(edges[i].from);
				const toNode = nodeMap.get(edges[i].to);
				if (!fromNode || !toNode) continue;

				// Use edge routing for metro-style segments
				const edgeKey = `${edges[i].from}->${edges[i].to}`;
				const routedEdge = edgeMap.get(edgeKey) ?? edgeMap.get(`${edges[i].to}->${edges[i].from}`);
				if (routedEdge) {
					for (const seg of routedEdge.segments) {
						result.push({
							key: `${p.id}-${edgeKey}-${age}-${seg.x1}-${seg.y1}`,
							x1: seg.x1,
							y1: seg.y1,
							x2: seg.x2,
							y2: seg.y2,
							color,
							opacity: OPACITY_LEVELS[age] ?? 0
						});
					}
				} else {
					// Straight line fallback
					result.push({
						key: `${p.id}-${edgeKey}-${age}`,
						x1: fromNode.x,
						y1: fromNode.y,
						x2: toNode.x,
						y2: toNode.y,
						color,
						opacity: OPACITY_LEVELS[age] ?? 0
					});
				}
			}
		}
		return result;
	});
</script>

{#snippet dagContent()}
	<defs>
		<filter id="player-glow" x="-50%" y="-50%" width="200%" height="200%">
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

	<!-- Player path polylines or trailing segments -->
	{#if !follow}
		{#each playerPaths as path (path.id)}
			<polyline
				points={path.points}
				fill="none"
				stroke={path.color}
				stroke-width="4"
				stroke-linecap="round"
				stroke-linejoin="round"
				opacity={hasHighlight && !highlightIds!.has(path.id) ? 0 : 0.8}
				class="player-path"
			>
				<title>{path.displayName}</title>
			</polyline>
		{/each}
	{:else}
		{#each trailingPaths as segment (segment.key)}
			<line
				x1={segment.x1}
				y1={segment.y1}
				x2={segment.x2}
				y2={segment.y2}
				stroke={segment.color}
				stroke-width="4"
				stroke-linecap="round"
				opacity={segment.opacity}
			/>
		{/each}
	{/if}

	<!-- Nodes -->
	{#each layout.nodes as node}
		<g class="dag-node" data-type={node.type} data-node-id={node.id}>
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

			<!-- Death icon (opposite side of label) -->
			{#if !hideLabels && nodesWithDeaths.has(node.id)}
				<text
					x={node.x}
					y={labelAbove.has(node.id)
						? node.y + nodeRadius(node) + LABEL_OFFSET_Y - 2
						: node.y - nodeRadius(node) - 6}
					text-anchor="middle"
					font-size={LABEL_FONT_SIZE - 1}
					class="death-icon"
					class:transparent-label={transparent}>💀</text
				>
			{/if}

			<!-- Label -->
			{#if !hideLabels}
				<text
					x={labelX(node)}
					y={labelY(node)}
					text-anchor={labelAbove.has(node.id) ? 'start' : 'end'}
					font-size={LABEL_FONT_SIZE}
					fill={LABEL_COLOR}
					class="dag-label"
					class:transparent-label={transparent}
					transform="rotate(-30, {labelX(node)}, {labelY(node)})"
				>
					{truncateLabel(node.displayName)}
				</text>
			{/if}
		</g>
	{/each}

	<!-- Live dots or static final dots -->
	{#if showLiveDots}
		<LivePlayerDots {participants} {nodeMap} {raceStatus} preRace={raceStatus === 'setup'} />
	{:else}
		{#each playerPaths as path (path.id)}
			<circle
				cx={path.finalX}
				cy={path.finalY}
				r={RACER_DOT_RADIUS}
				fill={path.color}
				filter="url(#player-glow)"
				opacity={hasHighlight && !highlightIds!.has(path.id) ? 0 : 1}
				class="player-dot"
				data-node-id={path.finalNodeId}
			>
				<title>{path.displayName}</title>
			</circle>
		{/each}
	{/if}
{/snippet}

{#if layout.nodes.length > 0}
	<div bind:this={dagContainer}>
		{#if follow}
			<FollowViewport
				width={layout.width}
				height={layout.height}
				{participants}
				{nodeMap}
				{raceStatus}
				{transparent}
			>
				{@render dagContent()}
			</FollowViewport>
		{:else}
			<ZoomableSvg
				width={layout.width}
				height={layout.height}
				{transparent}
				onnodeclick={onNodeClick}
				onpanstart={closePopup}
			>
				{@render dagContent()}
			</ZoomableSvg>
		{/if}
		{#if popupData}
			<NodePopup data={popupData} x={popupX} y={popupY} onclose={closePopup} />
		{/if}
	</div>
{/if}

<style>
	.dag-label {
		user-select: none;
		cursor: pointer;
		font-family:
			system-ui,
			-apple-system,
			sans-serif;
		paint-order: stroke;
		stroke: var(--color-surface, #1a1a2e);
		stroke-width: 4px;
		stroke-linejoin: round;
	}

	.transparent-label {
		stroke: transparent;
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

	.player-path {
		transition: opacity 200ms ease;
	}

	.player-dot {
		pointer-events: auto;
		cursor: pointer;
		transition: opacity 200ms ease;
	}
</style>
