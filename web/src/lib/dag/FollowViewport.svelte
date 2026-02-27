<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import type { PositionedNode } from './types';
	import { PLAYER_COLORS } from './constants';

	interface Props {
		width: number;
		height: number;
		participants: WsParticipant[];
		nodeMap: Map<string, PositionedNode>;
		raceStatus?: string;
		transparent?: boolean;
		maxLayers?: number;
		children: import('svelte').Snippet;
	}

	let {
		width,
		height,
		participants,
		nodeMap,
		raceStatus,
		transparent = false,
		maxLayers = 5,
		children
	}: Props = $props();

	// Find the X range of all layers from the layout
	let layerXPositions = $derived.by(() => {
		const xs = new Map<number, number>();
		for (const node of nodeMap.values()) {
			if (!xs.has(node.layer) || node.x < xs.get(node.layer)!) {
				xs.set(node.layer, node.x);
			}
		}
		return xs;
	});

	let totalLayers = $derived(layerXPositions.size);
	let minX = $derived(nodeMap.size > 0 ? Math.min(...[...nodeMap.values()].map((n) => n.x)) : 0);
	let maxX = $derived(
		nodeMap.size > 0 ? Math.max(...[...nodeMap.values()].map((n) => n.x)) : width
	);

	// Max visible layers: from prop, clamped to at least 3
	let maxVisibleLayers = $derived(Math.max(3, maxLayers));

	// Compute target viewport based on race status
	interface Viewport {
		centerX: number;
		centerY: number;
		visibleWidth: number;
		visibleHeight: number;
	}

	let targetViewport: Viewport = $derived.by(() => {
		if (raceStatus === 'finished') {
			// Show full DAG
			return {
				centerX: width / 2,
				centerY: height / 2,
				visibleWidth: width,
				visibleHeight: height
			};
		}

		const activePlayers = participants.filter((p) => p.status === 'playing');

		if (raceStatus === 'setup' || activePlayers.length === 0) {
			// Zoom on start area — find start node
			let startX = minX;
			for (const node of nodeMap.values()) {
				if (node.type === 'start') {
					startX = node.x;
					break;
				}
			}
			// Show maxVisibleLayers worth of width from the start
			const layerWidth = totalLayers > 1 ? (maxX - minX) / (totalLayers - 1) : 100;
			const visibleWidth = layerWidth * maxVisibleLayers;
			return {
				centerX: startX + visibleWidth / 2 - layerWidth / 2,
				centerY: height / 2,
				visibleWidth,
				visibleHeight: height
			};
		}

		// Running: compute from active player positions
		const playerLayers = activePlayers.map((p) => p.current_layer);
		const maxLayer = Math.max(...playerLayers);

		// Convert layers to X positions (interpolates between nearest known layers)
		const sortedXs = [...layerXPositions.entries()].sort((a, b) => a[0] - b[0]);
		const layerToX = (layer: number): number => {
			const exact = sortedXs.find(([l]) => l === layer);
			if (exact) return exact[1];
			// Interpolate between nearest floor/ceil layers
			const floor = Math.floor(layer);
			const ceil = Math.ceil(layer);
			const floorEntry = sortedXs.find(([l]) => l === floor);
			const ceilEntry = sortedXs.find(([l]) => l === ceil);
			if (floorEntry && ceilEntry) {
				const frac = layer - floor;
				return floorEntry[1] + (ceilEntry[1] - floorEntry[1]) * frac;
			}
			if (floorEntry) return floorEntry[1];
			if (ceilEntry) return ceilEntry[1];
			// Fallback for out-of-range layers
			const layerWidth = totalLayers > 1 ? (maxX - minX) / (totalLayers - 1) : 100;
			return minX + layer * layerWidth;
		};

		// Barycenter of active players
		const avgLayer = playerLayers.reduce((s, l) => s + l, 0) / playerLayers.length;
		let centerX = layerToX(avgLayer);

		// Visible width: at least maxVisibleLayers, clamped to full DAG width
		const layerWidth = totalLayers > 1 ? (maxX - minX) / (totalLayers - 1) : 100;
		const visibleWidth = Math.min(layerWidth * maxVisibleLayers, width);
		const halfVisible = visibleWidth / 2;

		// Guarantee leader is always visible: if the leader's X is outside
		// the right edge of the viewport, shift center right to include them
		const leaderX = layerToX(maxLayer);
		const viewRight = centerX + halfVisible;
		if (leaderX > viewRight) {
			centerX = leaderX - halfVisible + layerWidth * 0.5; // small margin
		}

		// Clamp center so we don't go past first/last layer
		const clampedCenterX = Math.max(
			minX + halfVisible,
			Math.min(maxX - halfVisible, centerX)
		);

		return {
			centerX: clampedCenterX,
			centerY: height / 2,
			visibleWidth,
			visibleHeight: height
		};
	});

	// Smooth interpolation of viewBox via requestAnimationFrame
	const LERP_SPEED = 3; // Higher = faster convergence
	let currentVB = $state({ x: 0, y: 0, w: 0, h: 0 });
	let initialized = false;
	let frameId: number;

	$effect(() => {
		const target = targetViewport;
		const targetVB = {
			x: target.centerX - target.visibleWidth / 2,
			y: target.centerY - target.visibleHeight / 2,
			w: target.visibleWidth,
			h: target.visibleHeight
		};

		if (!initialized) {
			currentVB = { ...targetVB };
			initialized = true;
			return;
		}

		let lastTime = performance.now();
		function animate() {
			const now = performance.now();
			const dt = Math.min((now - lastTime) / 1000, 0.1); // Cap delta at 100ms
			lastTime = now;

			const t = 1 - Math.exp(-LERP_SPEED * dt);
			currentVB = {
				x: currentVB.x + (targetVB.x - currentVB.x) * t,
				y: currentVB.y + (targetVB.y - currentVB.y) * t,
				w: currentVB.w + (targetVB.w - currentVB.w) * t,
				h: currentVB.h + (targetVB.h - currentVB.h) * t
			};

			// Stop animating when close enough
			const dx = Math.abs(currentVB.x - targetVB.x);
			const dw = Math.abs(currentVB.w - targetVB.w);
			if (dx > 0.5 || dw > 0.5) {
				frameId = requestAnimationFrame(animate);
			}
		}
		frameId = requestAnimationFrame(animate);
		return () => cancelAnimationFrame(frameId);
	});

	let viewBox = $derived(`${currentVB.x} ${currentVB.y} ${currentVB.w} ${currentVB.h}`);

	// Off-screen indicators: players outside the current viewport
	interface OffscreenIndicator {
		participantId: string;
		displayName: string;
		color: string;
		side: 'left' | 'right';
		yPercent: number;
	}

	let offscreenIndicators = $derived.by(() => {
		if (raceStatus !== 'running' || currentVB.h <= 0) return [];

		const vLeft = currentVB.x;
		const vRight = currentVB.x + currentVB.w;
		const indicators: OffscreenIndicator[] = [];

		for (const p of participants) {
			if (p.status !== 'playing' || !p.current_zone) continue;
			const node = nodeMap.get(p.current_zone);
			if (!node) continue;

			if (node.x < vLeft) {
				indicators.push({
					participantId: p.id,
					displayName: p.twitch_display_name || p.twitch_username,
					color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
					side: 'left',
					yPercent: ((node.y - currentVB.y) / currentVB.h) * 100
				});
			} else if (node.x > vRight) {
				indicators.push({
					participantId: p.id,
					displayName: p.twitch_display_name || p.twitch_username,
					color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
					side: 'right',
					yPercent: ((node.y - currentVB.y) / currentVB.h) * 100
				});
			}
		}
		return indicators;
	});
</script>

<div class="follow-container" class:transparent>
	{#if width > 0 && height > 0}
		<svg {viewBox} preserveAspectRatio="xMidYMid meet" class="follow-svg" role="img">
			{@render children()}
		</svg>

		<!-- Off-screen indicators (rendered as HTML overlays) -->
		{#each offscreenIndicators as ind (ind.participantId)}
			<div
				class="offscreen-indicator"
				class:left={ind.side === 'left'}
				class:right={ind.side === 'right'}
				style="--player-color: {ind.color}; top: {Math.max(5, Math.min(95, ind.yPercent))}%;"
			>
				<span class="offscreen-chevron">{ind.side === 'left' ? '\u25C0' : '\u25B6'}</span>
				<span class="offscreen-name">{ind.displayName}</span>
			</div>
		{/each}
	{/if}
</div>

<style>
	.follow-container {
		position: relative;
		width: 100%;
		background: var(--color-surface, #1a1a2e);
		border-radius: var(--radius-lg, 8px);
		min-height: 200px;
		display: flex;
		align-items: center;
		justify-content: center;
		overflow: hidden;
	}

	.follow-container.transparent {
		background: transparent;
		border-radius: 0;
	}

	.follow-svg {
		display: block;
		width: 100%;
		min-width: 600px;
		user-select: none;
	}

	.offscreen-indicator {
		position: absolute;
		display: flex;
		align-items: center;
		gap: 0.25rem;
		padding: 0.2rem 0.5rem;
		font-size: 11px;
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		color: var(--player-color);
		text-shadow: 0 1px 3px rgba(0, 0, 0, 0.8);
		pointer-events: none;
		transform: translateY(-50%);
	}

	.offscreen-indicator.left {
		left: 4px;
	}

	.offscreen-indicator.right {
		right: 4px;
	}

	.offscreen-chevron {
		font-size: 14px;
	}

	.offscreen-name {
		font-weight: 600;
		white-space: nowrap;
	}
</style>
