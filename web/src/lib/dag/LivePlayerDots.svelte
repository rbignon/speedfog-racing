<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import type { PositionedNode } from './types';
	import {
		PLAYER_COLORS,
		RACER_DOT_RADIUS,
		LIVE_ORBIT_RADIUS,
		LIVE_ORBIT_PERIOD_MS,
		LIVE_SKULL_ANIM_MS,
		LIVE_SKULL_PEAK_SCALE,
		LIVE_FINISHED_X_OFFSET,
		LIVE_START_X_OFFSET
	} from './constants';

	interface Props {
		participants: WsParticipant[];
		nodeMap: Map<string, PositionedNode>;
		raceStatus?: string;
		/** Show dots in pre-race position (aligned left of start) */
		preRace?: boolean;
	}

	let { participants, nodeMap, raceStatus, preRace = false }: Props = $props();

	// Wall-clock elapsed time for orbit animation
	let elapsed = $state(0);
	let frameId: number;

	$effect(() => {
		const start = performance.now();
		function tick() {
			elapsed = performance.now() - start;
			frameId = requestAnimationFrame(tick);
		}
		frameId = requestAnimationFrame(tick);
		return () => cancelAnimationFrame(frameId);
	});

	// Find start node (type === 'start') for pre-race positioning
	let startNode = $derived.by(() => {
		for (const node of nodeMap.values()) {
			if (node.type === 'start') return node;
		}
		return null;
	});

	// Find final boss node for finished positioning
	let finalBossNode = $derived.by(() => {
		for (const node of nodeMap.values()) {
			if (node.type === 'final_boss') return node;
		}
		return null;
	});

	// Track previous death counts to detect new deaths
	let prevDeaths = $state(new Map<string, number>());
	interface SkullAnim {
		id: string;
		participantId: string;
		nodeId: string;
		startTime: number;
	}
	let skulls = $state<SkullAnim[]>([]);

	$effect(() => {
		const now = performance.now();
		const newSkulls: SkullAnim[] = [];
		for (const p of participants) {
			const prev = prevDeaths.get(p.id) ?? 0;
			if (p.death_count > prev && p.current_zone) {
				for (let i = 0; i < p.death_count - prev; i++) {
					newSkulls.push({
						id: `${p.id}-${now}-${i}`,
						participantId: p.id,
						nodeId: p.current_zone,
						startTime: now
					});
				}
			}
			prevDeaths.set(p.id, p.death_count);
		}
		if (newSkulls.length > 0) {
			skulls = [
				...skulls.filter((s) => performance.now() - s.startTime < LIVE_SKULL_ANIM_MS),
				...newSkulls
			];
		}
	});

	// Clean up expired skulls periodically
	$effect(() => {
		// Re-run when elapsed changes (every frame)
		void elapsed;
		skulls = skulls.filter((s) => performance.now() - s.startTime < LIVE_SKULL_ANIM_MS);
	});

	interface DotPosition {
		participantId: string;
		x: number;
		y: number;
		color: string;
		displayName: string;
		opacity: number;
	}

	let dots: DotPosition[] = $derived.by(() => {
		const result: DotPosition[] = [];
		const playingAtNode = new Map<string, number>();

		for (let i = 0; i < participants.length; i++) {
			const p = participants[i];
			const color = PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
			const displayName = p.twitch_display_name || p.twitch_username;

			if (preRace && startNode) {
				// Pre-race: align left of start node
				const spacing = RACER_DOT_RADIUS * 2;
				const totalSpread = (participants.length - 1) * spacing;
				const yOffset = -totalSpread / 2 + i * spacing;
				result.push({
					participantId: p.id,
					x: startNode.x + LIVE_START_X_OFFSET,
					y: startNode.y + yOffset,
					color,
					displayName,
					opacity: 1
				});
				continue;
			}

			if (p.status === 'finished' && finalBossNode) {
				// Finished: align right of final boss
				const finishedPlayers = participants.filter((pp) => pp.status === 'finished');
				const idx = finishedPlayers.indexOf(p);
				const spacing = RACER_DOT_RADIUS * 2;
				const totalSpread = (finishedPlayers.length - 1) * spacing;
				const yOffset = -totalSpread / 2 + idx * spacing;
				result.push({
					participantId: p.id,
					x: finalBossNode.x + LIVE_FINISHED_X_OFFSET,
					y: finalBossNode.y + yOffset,
					color,
					displayName,
					opacity: 1
				});
				continue;
			}

			if (p.status === 'abandoned' && p.current_zone) {
				const node = nodeMap.get(p.current_zone);
				if (node) {
					result.push({
						participantId: p.id,
						x: node.x,
						y: node.y,
						color,
						displayName,
						opacity: 0.35
					});
				}
				continue;
			}

			if ((p.status === 'playing' || p.status === 'ready') && p.current_zone) {
				const node = nodeMap.get(p.current_zone);
				if (node) {
					// Count how many players are at this node for phase offset
					const countAtNode = playingAtNode.get(p.current_zone) ?? 0;
					playingAtNode.set(p.current_zone, countAtNode + 1);

					const phaseOffset = (countAtNode / Math.max(participants.length, 1)) * Math.PI * 2;
					const angle = phaseOffset + (elapsed / LIVE_ORBIT_PERIOD_MS) * Math.PI * 2;
					result.push({
						participantId: p.id,
						x: node.x + Math.cos(angle) * LIVE_ORBIT_RADIUS,
						y: node.y + Math.sin(angle) * LIVE_ORBIT_RADIUS,
						color,
						displayName,
						opacity: 1
					});
				}
				continue;
			}
		}
		return result;
	});

	function skullScale(progress: number): number {
		if (progress < 0.3) return (progress / 0.3) * LIVE_SKULL_PEAK_SCALE;
		if (progress < 0.5) {
			const overshoot = LIVE_SKULL_PEAK_SCALE - 1.0;
			return LIVE_SKULL_PEAK_SCALE - ((progress - 0.3) / 0.2) * overshoot;
		}
		return 1.0;
	}

	function skullOpacity(progress: number): number {
		if (progress < 0.5) return 1;
		return 1 - (progress - 0.5) / 0.5;
	}
</script>

<!-- Player dots -->
{#each dots as dot (dot.participantId)}
	<circle
		cx={dot.x}
		cy={dot.y}
		r={RACER_DOT_RADIUS}
		fill={dot.color}
		opacity={dot.opacity}
		filter={dot.opacity < 1 ? undefined : 'url(#live-player-glow)'}
		class="live-dot"
	>
		<title>{dot.displayName}</title>
	</circle>
{/each}

<!-- Skull animations -->
{#each skulls as skull (skull.id)}
	{@const pos = nodeMap.get(skull.nodeId)}
	{@const progress = (performance.now() - skull.startTime) / LIVE_SKULL_ANIM_MS}
	{#if pos && progress < 1}
		<text
			x={pos.x}
			y={pos.y}
			text-anchor="middle"
			dominant-baseline="central"
			font-size={18 * skullScale(progress)}
			opacity={skullOpacity(progress)}
			class="skull-anim">&#x1F480;</text
		>
	{/if}
{/each}

<style>
	.live-dot {
		pointer-events: none;
	}
	.skull-anim {
		pointer-events: none;
	}
</style>
