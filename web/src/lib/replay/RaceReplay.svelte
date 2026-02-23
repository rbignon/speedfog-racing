<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import type { ReplayState } from './types';
	import { REPLAY_DEFAULTS } from './types';
	import {
		buildReplayParticipants,
		collectSkullEvents,
		igtToReplayMs,
		replayMsToIgt
	} from './timeline';
	import { mapHighlightsToTimeline } from './highlights';
	import { computeHighlights } from '$lib/highlights';
	import { parseDagGraph } from '$lib/dag/types';
	import { computeLayout } from '$lib/dag/layout';
	import ZoomableSvg from '$lib/dag/ZoomableSvg.svelte';
	import DagBaseLayer from '$lib/dag/DagBaseLayer.svelte';
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
	let animationFrameId: number | null = null;
	let lastFrameTime: number | null = null;

	// Leader tracking — updated by ReplayDag via callback to avoid double computation
	let leaderId: string | null = $state(null);
	let previousLeader: string | null = $state(null);

	function handleLeaderChange(newLeaderId: string | null) {
		previousLeader = leaderId;
		leaderId = newLeaderId;
	}

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

				<DagBaseLayer {layout} {labelAbove} />

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
						{leaderId}
						{previousLeader}
						onleaderchange={handleLeaderChange}
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
	}

	.replay-dag-container {
		position: relative;
		background: var(--color-surface);
		border-radius: var(--radius-lg) var(--radius-lg) 0 0;
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

</style>
