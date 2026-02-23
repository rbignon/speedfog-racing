<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import type { ReplayState } from './types';
	import { REPLAY_DEFAULTS } from './types';
	import {
		buildReplayParticipants,
		collectSkullEvents,
		igtToReplayMs,
		replayMsToIgt,
		computePlayerPosition,
		computeLeader
	} from './timeline';
	import { mapHighlightsToTimeline } from './highlights';
	import { computeHighlights } from '$lib/highlights';
	import { parseDagGraph } from '$lib/dag/types';
	import { computeLayout } from '$lib/dag/layout';
	import ZoomableSvg from '$lib/dag/ZoomableSvg.svelte';
	import {
		NODE_RADIUS,
		NODE_COLORS,
		BG_COLOR,
		EDGE_STROKE_WIDTH,
		EDGE_COLOR,
		LABEL_MAX_CHARS,
		LABEL_FONT_SIZE,
		LABEL_COLOR,
		LABEL_OFFSET_Y
	} from '$lib/dag/constants';
	import type { PositionedNode } from '$lib/dag/types';
	import ReplayDag from './ReplayDag.svelte';
	import ReplayControls from './ReplayControls.svelte';

	interface Props {
		graphJson: Record<string, unknown>;
		participants: WsParticipant[];
	}

	let { graphJson, participants }: Props = $props();

	// Pre-compute all replay data (runs once, memoized via $derived)
	let graph = $derived(parseDagGraph(graphJson));
	let layout = $derived(computeLayout(graph));

	let nodePositions = $derived.by(() => {
		const map = new Map<string, { x: number; y: number }>();
		for (const node of layout.nodes) {
			map.set(node.id, { x: node.x, y: node.y });
		}
		return map;
	});

	let nodeInfo = $derived.by(() => {
		const map = new Map<string, { layer: number; type: string }>();
		const nodes = (graphJson as { nodes: Record<string, Record<string, unknown>> }).nodes;
		if (!nodes) return map;
		for (const [id, data] of Object.entries(nodes)) {
			map.set(id, {
				layer: (data.layer as number) ?? 0,
				type: (data.type as string) ?? 'mini_dungeon'
			});
		}
		return map;
	});

	let replayParticipants = $derived(buildReplayParticipants(participants, graphJson));
	let maxIgt = $derived(Math.max(...replayParticipants.map((rp) => rp.totalIgt), 0));
	let skullEvents = $derived(collectSkullEvents(replayParticipants));
	let highlights = $derived(computeHighlights(participants, graphJson));
	let commentaryEvents = $derived(mapHighlightsToTimeline(highlights, replayParticipants));

	// Label placement (same logic as MetroDagFull)
	let labelAbove = $derived.by(() => {
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

	// Animation state
	let replayState: ReplayState = $state('idle');
	let speed = $state(1);
	let replayElapsedMs = $state(0);
	let currentIgt = $state(0);
	let previousLeader: string | null = $state(null);
	let animationFrameId: number | null = null;
	let lastFrameTime: number | null = null;

	function tick(timestamp: number) {
		if (lastFrameTime === null) {
			lastFrameTime = timestamp;
			animationFrameId = requestAnimationFrame(tick);
			return;
		}

		const delta = (timestamp - lastFrameTime) * speed;
		lastFrameTime = timestamp;
		replayElapsedMs += delta;

		// Map replay elapsed to IGT
		currentIgt = replayMsToIgt(replayElapsedMs, maxIgt);

		// Track leader for flash effect
		const snapshots = [];
		for (let i = 0; i < replayParticipants.length; i++) {
			const rp = replayParticipants[i];
			const phaseOffset = (i / replayParticipants.length) * Math.PI * 2;
			const snap = computePlayerPosition(
				rp,
				currentIgt,
				nodePositions,
				nodeInfo,
				phaseOffset,
				replayElapsedMs
			);
			if (snap) snapshots.push(snap);
		}
		const newLeader = computeLeader(snapshots);
		if (newLeader !== previousLeader) {
			previousLeader = newLeader;
		}

		if (replayElapsedMs >= REPLAY_DEFAULTS.DURATION_MS) {
			replayState = 'finished';
			currentIgt = maxIgt;
			animationFrameId = null;
			lastFrameTime = null;
			return;
		}

		animationFrameId = requestAnimationFrame(tick);
	}

	function play() {
		if (replayState === 'finished') {
			// Restart
			replayElapsedMs = 0;
			currentIgt = 0;
			previousLeader = null;
		}
		replayState = 'playing';
		lastFrameTime = null;
		animationFrameId = requestAnimationFrame(tick);
	}

	function pause() {
		replayState = 'paused';
		if (animationFrameId !== null) {
			cancelAnimationFrame(animationFrameId);
			animationFrameId = null;
		}
		lastFrameTime = null;
	}

	function seek(progress: number) {
		replayElapsedMs = progress * REPLAY_DEFAULTS.DURATION_MS;
		currentIgt = replayMsToIgt(replayElapsedMs, maxIgt);
		if (replayState === 'finished' && progress < 1) {
			replayState = 'paused';
		}
	}

	function setSpeed(s: number) {
		speed = s;
	}

	// Cleanup on unmount
	$effect(() => {
		return () => {
			if (animationFrameId !== null) {
				cancelAnimationFrame(animationFrameId);
			}
		};
	});

	let progress = $derived(
		REPLAY_DEFAULTS.DURATION_MS > 0 ? replayElapsedMs / REPLAY_DEFAULTS.DURATION_MS : 0
	);

	// Commentary for the bottom overlay
	let activeCommentary = $derived.by(() => {
		const replayMs = igtToReplayMs(currentIgt, maxIgt);
		for (let i = commentaryEvents.length - 1; i >= 0; i--) {
			const ev = commentaryEvents[i];
			const evReplayMs = igtToReplayMs(ev.igtMs, maxIgt);
			const age = replayMs - evReplayMs;
			if (age >= 0 && age < REPLAY_DEFAULTS.COMMENTARY_DURATION_MS) {
				const fadeProgress = age / REPLAY_DEFAULTS.COMMENTARY_DURATION_MS;
				const opacity = fadeProgress > 0.8 ? 1 - (fadeProgress - 0.8) / 0.2 : 1;
				return {
					title: ev.highlight.title,
					text: ev.highlight.segments
						.map((s) => (s.type === 'text' ? s.value : s.name))
						.join(''),
					opacity
				};
			}
		}
		return null;
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

{#if replayParticipants.length >= 2 && maxIgt > 0}
	<div class="race-replay">
		<div class="replay-dag-container">
			<ZoomableSvg width={layout.width} height={layout.height}>
				<defs>
					<filter id="replay-player-glow" x="-50%" y="-50%" width="200%" height="200%">
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

				<!-- Nodes -->
				{#each layout.nodes as node}
					<g class="dag-node" data-type={node.type} data-node-id={node.id}>
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
							<circle
								cx={node.x}
								cy={node.y}
								r={nodeRadius(node) * 0.5}
								fill={nodeColor(node)}
							/>
						{/if}

						<text
							x={labelX(node)}
							y={labelY(node)}
							text-anchor={labelAbove.has(node.id) ? 'start' : 'end'}
							font-size={LABEL_FONT_SIZE}
							fill={LABEL_COLOR}
							class="dag-label"
							transform="rotate(-30, {labelX(node)}, {labelY(node)})"
						>{truncateLabel(node.displayName)}</text>
					</g>
				{/each}

				<!-- Animated overlay -->
				{#if replayState !== 'idle'}
					<ReplayDag
						{currentIgt}
						{replayElapsedMs}
						{maxIgt}
						{replayParticipants}
						{skullEvents}
						{nodePositions}
						{nodeInfo}
						{previousLeader}
					/>
				{/if}
			</ZoomableSvg>

			<!-- Commentary overlay (HTML, positioned over the SVG) -->
			{#if activeCommentary}
				<div class="commentary" style="opacity: {activeCommentary.opacity}">
					<span class="commentary-title">{activeCommentary.title}</span>
					<span class="commentary-text">{activeCommentary.text}</span>
				</div>
			{/if}

		</div>

		<ReplayControls
			{replayState}
			{progress}
			{speed}
			onplay={play}
			onpause={pause}
			onseek={seek}
			onspeed={setSpeed}
		/>
	</div>
{/if}

<style>
	.race-replay {
		display: flex;
		flex-direction: column;
		gap: 0.75rem;
	}

	.replay-dag-container {
		position: relative;
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		overflow: hidden;
	}

	.commentary {
		position: absolute;
		bottom: 1rem;
		left: 50%;
		transform: translateX(-50%);
		background: rgba(15, 25, 35, 0.9);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 0.5rem 1.25rem;
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.15rem;
		transition: opacity 0.3s ease;
		pointer-events: none;
	}

	.commentary-title {
		font-weight: 600;
		font-size: var(--font-size-base);
		color: var(--color-gold);
	}

	.commentary-text {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.dag-node {
		cursor: default;
	}

	.dag-label {
		user-select: none;
		font-family: system-ui, -apple-system, sans-serif;
		paint-order: stroke;
		stroke: var(--color-surface, #1a1a2e);
		stroke-width: 4px;
		stroke-linejoin: round;
	}
</style>
