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
		DRAW_PHASE_DURATION_MS,
		DRAW_TO_RACE_PAUSE_MS,
		HERO_RACER_COUNT,
		RACER_DOT_RADIUS,
		RACE_LOOP_DURATION_MS,
		HERO_RACER_COLORS,
	} from './constants';
	import {
		enumerateAllPaths,
		pickRacerPaths,
		buildRacerPath,
		computeEdgeDrawTimings,
		computeNodeAppearTimings,
		interpolatePosition,
		segmentLength,
	} from './animation';
	import type { DagLayout, PositionedNode, RoutedEdge } from './types';
	import type { RacerPath, EdgeDrawTiming, NodeAppearTiming } from './animation';

	let { graphJson }: { graphJson: Record<string, unknown> } = $props();

	// Compute layout from graph data
	let layout: DagLayout = $derived.by(() => {
		const graph = parseDagGraph(graphJson);
		return computeLayout(graph);
	});

	// Compute animation data
	let edgeTimings: EdgeDrawTiming[] = $derived(computeEdgeDrawTimings(layout));
	let nodeTimings: NodeAppearTiming[] = $derived(computeNodeAppearTimings(layout, edgeTimings));

	let racerPaths: RacerPath[] = $derived.by(() => {
		const allPaths = enumerateAllPaths(layout);
		const selected = pickRacerPaths(allPaths, HERO_RACER_COUNT);
		return selected.map((nodeIds) => buildRacerPath(nodeIds, layout));
	});

	// Build timing maps for O(1) lookups in template
	let edgeTimingMap = $derived.by(() => {
		const map = new Map<string, EdgeDrawTiming>();
		for (const t of edgeTimings) {
			map.set(`${t.fromId}->${t.toId}`, t);
		}
		return map;
	});

	let nodeTimingMap = $derived.by(() => {
		const map = new Map<string, number>();
		for (const t of nodeTimings) {
			map.set(t.nodeId, t.fraction);
		}
		return map;
	});

	// Animation phase state
	let racerPositions = $state<{ x: number; y: number }[]>([]);
	let showRacers = $state(false);

	// Racer speed multipliers — fastest finishes first, slowest last
	const RACER_SPEEDS = [1.15, 1.0, 0.88, 0.76];

	/** Pause at the finish line before restarting (ms) */
	const FINISH_PAUSE_MS = 2000;

	// Detect prefers-reduced-motion
	let prefersReducedMotion = $state(false);

	$effect(() => {
		if (typeof window === 'undefined') return;

		const mql = window.matchMedia('(prefers-reduced-motion: reduce)');
		prefersReducedMotion = mql.matches;

		function onChange(e: MediaQueryListEvent) {
			prefersReducedMotion = e.matches;
		}
		mql.addEventListener('change', onChange);
		return () => mql.removeEventListener('change', onChange);
	});

	// Racing phase animation loop
	$effect(() => {
		if (prefersReducedMotion || racerPaths.length === 0) {
			// Show static dots at endpoints
			racerPositions = racerPaths.map((rp) => {
				const last = rp.waypoints[rp.waypoints.length - 1];
				return last ? { x: last.x, y: last.y } : { x: 0, y: 0 };
			});
			showRacers = !prefersReducedMotion;
			return;
		}

		let rafId: number;
		let phaseTimeout: ReturnType<typeof setTimeout>;
		let restartTimeout: ReturnType<typeof setTimeout>;
		let raceStartTime: number;
		let cancelled = false;

		function startRace() {
			if (cancelled) return;
			showRacers = true;
			raceStartTime = performance.now();
			rafId = requestAnimationFrame(animate);
		}

		function animate(now: number) {
			if (cancelled) return;
			const elapsed = now - raceStartTime;
			// Linear progress: 0 → 1 over RACE_LOOP_DURATION_MS
			const rawProgress = elapsed / RACE_LOOP_DURATION_MS;

			let allFinished = true;
			racerPositions = racerPaths.map((rp, i) => {
				const speed = RACER_SPEEDS[i % RACER_SPEEDS.length];
				const progress = Math.min(rawProgress * speed, 1);
				if (progress < 1) allFinished = false;
				return interpolatePosition(rp, progress);
			});

			if (allFinished) {
				// All racers finished — pause then restart
				restartTimeout = setTimeout(startRace, FINISH_PAUSE_MS);
			} else {
				rafId = requestAnimationFrame(animate);
			}
		}

		// Wait for draw phase + pause, then start first race
		phaseTimeout = setTimeout(startRace, DRAW_PHASE_DURATION_MS + DRAW_TO_RACE_PAUSE_MS);

		return () => {
			cancelled = true;
			clearTimeout(phaseTimeout);
			clearTimeout(restartTimeout);
			if (rafId) cancelAnimationFrame(rafId);
		};
	});

	// Helpers for edge segment CSS custom properties
	function getEdgeDrawDelay(edge: RoutedEdge): number {
		const timing = edgeTimingMap.get(`${edge.fromId}->${edge.toId}`);
		if (!timing) return 0;
		return timing.startFraction * DRAW_PHASE_DURATION_MS;
	}

	function getEdgeDrawDuration(edge: RoutedEdge): number {
		const timing = edgeTimingMap.get(`${edge.fromId}->${edge.toId}`);
		if (!timing) return 0;
		return (timing.endFraction - timing.startFraction) * DRAW_PHASE_DURATION_MS;
	}

	function getNodeDelay(node: PositionedNode): number {
		const fraction = nodeTimingMap.get(node.id) ?? 0;
		return fraction * DRAW_PHASE_DURATION_MS;
	}

	function nodeRadius(node: PositionedNode): number {
		return NODE_RADIUS[node.type];
	}

	function nodeColor(node: PositionedNode): string {
		return NODE_COLORS[node.type];
	}
</script>

<div class="hero-dag-container">
	{#if layout.nodes.length > 0}
		<svg
			viewBox="0 0 {layout.width} {layout.height}"
			width="100%"
			preserveAspectRatio="xMidYMid meet"
			class="hero-dag-svg"
			aria-hidden="true"
		>
			<!-- Edge segments with draw animation -->
			{#each layout.edges as edge}
				{@const edgeDelay = getEdgeDrawDelay(edge)}
				{@const edgeDuration = getEdgeDrawDuration(edge)}
				{@const totalEdgeLen = edge.segments.reduce((s, seg) => s + segmentLength(seg), 0)}
				{#each edge.segments as seg, segIdx}
					{@const dashLen = segmentLength(seg)}
					{@const segFractionBefore = edge.segments.slice(0, segIdx).reduce((s, prev) => s + segmentLength(prev), 0) / (totalEdgeLen || 1)}
					{@const segFraction = dashLen / (totalEdgeLen || 1)}
					<line
						x1={seg.x1}
						y1={seg.y1}
						x2={seg.x2}
						y2={seg.y2}
						stroke={EDGE_COLOR}
						stroke-width={EDGE_STROKE_WIDTH}
						stroke-linecap="butt"
						opacity={EDGE_OPACITY}
						class="edge-segment"
						class:no-animation={prefersReducedMotion}
						style="
							--dash-length: {dashLen};
							--draw-delay: {edgeDelay + segFractionBefore * edgeDuration}ms;
							--draw-duration: {segFraction * edgeDuration}ms;
						"
					/>
				{/each}
			{/each}

			<!-- Nodes with fade-in -->
			{#each layout.nodes as node}
				<g
					class="dag-node"
					class:no-animation={prefersReducedMotion}
					style="--node-delay: {getNodeDelay(node)}ms;"
				>
					{#if node.type === 'start'}
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
						<circle
							cx={node.x}
							cy={node.y}
							r={nodeRadius(node)}
							fill={nodeColor(node)}
						/>
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
				</g>
			{/each}

			<!-- Racer dots -->
			{#if showRacers}
				{#each racerPositions as pos, i}
					<circle
						cx={pos.x}
						cy={pos.y}
						r={RACER_DOT_RADIUS}
						fill={HERO_RACER_COLORS[i % HERO_RACER_COLORS.length]}
						class="racer-dot"
						style="filter: drop-shadow(0 0 4px {HERO_RACER_COLORS[i % HERO_RACER_COLORS.length]});"
					/>
				{/each}
			{/if}
		</svg>
	{/if}
</div>

<style>
	.hero-dag-container {
		width: 100%;
		overflow: hidden;
		background: var(--color-surface, #1a1a2e);
	}

	.hero-dag-svg {
		display: block;
	}

	/* Edge draw animation */
	.edge-segment {
		stroke-dasharray: var(--dash-length);
		stroke-dashoffset: var(--dash-length);
		animation: draw-edge var(--draw-duration) linear var(--draw-delay) forwards;
	}

	.edge-segment.no-animation {
		stroke-dasharray: none;
		stroke-dashoffset: 0;
		animation: none;
	}

	@keyframes draw-edge {
		to {
			stroke-dashoffset: 0;
		}
	}

	/* Node fade-in */
	.dag-node {
		opacity: 0;
		animation: fade-in 200ms ease var(--node-delay) forwards;
	}

	.dag-node.no-animation {
		opacity: 1;
		animation: none;
	}

	@keyframes fade-in {
		to {
			opacity: 1;
		}
	}

	/* Racer dots */
	.racer-dot {
		transition: cx 16ms linear, cy 16ms linear;
	}
</style>
