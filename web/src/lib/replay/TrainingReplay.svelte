<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import type { ReplayState } from './types';
	import { REPLAY_DEFAULTS } from './types';
	import { buildReplayParticipants, collectSkullEvents, replayMsToIgt } from './timeline';
	import { parseDagGraph } from '$lib/dag/types';
	import { computeLayout } from '$lib/dag/layout';
	import type { PositionedNode } from '$lib/dag/types';
	import ZoomableSvg from '$lib/dag/ZoomableSvg.svelte';
	import DagBaseLayer from '$lib/dag/DagBaseLayer.svelte';
	import ReplayDag from './ReplayDag.svelte';
	import ReplayControls from './ReplayControls.svelte';

	interface Props {
		graphJson: Record<string, unknown>;
		/** The current player as a WsParticipant */
		currentPlayer: WsParticipant;
		/** Ghost participants (anonymous, will be rendered gray) */
		ghosts: WsParticipant[];
	}

	let { graphJson, currentPlayer, ghosts }: Props = $props();

	let allParticipants = $derived([currentPlayer, ...ghosts]);

	// Pre-compute layout
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

	let ghostIds = $derived(new Set(ghosts.map((g) => g.id)));

	let replayParticipants = $derived.by(() => {
		const rps = buildReplayParticipants(allParticipants, graphJson);
		// Override ghost colors to gray
		for (const rp of rps) {
			if (ghostIds.has(rp.id)) {
				rp.color = '#888888';
			}
		}
		return rps;
	});

	let maxIgt = $derived(Math.max(...replayParticipants.map((rp) => rp.totalIgt), 0));
	let skullEvents = $derived(collectSkullEvents(replayParticipants));

	// Label placement
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

	// Leader tracking
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
		if (replayState === 'idle' || (replayState === 'finished' && progress < 1)) {
			replayState = 'paused';
		}
	}

	function setSpeed(s: number) {
		speed = s;
	}

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
</script>

{#if replayParticipants.length >= 1 && maxIgt > 0}
	<div class="training-replay">
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
						{ghostIds}
						onleaderchange={handleLeaderChange}
					/>
				{/if}
			</ZoomableSvg>
		</div>

		<ReplayControls
			{replayState}
			{progress}
			{speed}
			ghostCount={ghosts.length}
			onplay={play}
			onpause={pause}
			onseek={seek}
			onspeed={setSpeed}
		/>
	</div>
{/if}

<style>
	.training-replay {
		display: flex;
		flex-direction: column;
	}

	.replay-dag-container {
		position: relative;
		background: var(--color-surface);
		border-radius: var(--radius-lg) var(--radius-lg) 0 0;
		overflow: hidden;
	}
</style>
