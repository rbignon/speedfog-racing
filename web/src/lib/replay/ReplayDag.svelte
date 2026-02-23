<script lang="ts">
	import type { ReplayParticipant, PlayerSnapshot, SkullEvent, CommentaryEvent } from './types';
	import { REPLAY_DEFAULTS } from './types';
	import { computePlayerPosition, computeLeader, computeNodeHeat, igtToReplayMs } from './timeline';
	import { RACER_DOT_RADIUS } from '$lib/dag/constants';

	interface Props {
		/** Current race IGT in the replay */
		currentIgt: number;
		/** Wall-clock elapsed replay time (for orbit animation) */
		replayElapsedMs: number;
		maxIgt: number;
		replayParticipants: ReplayParticipant[];
		skullEvents: SkullEvent[];
		nodePositions: Map<string, { x: number; y: number }>;
		nodeInfo: Map<string, { layer: number; type: string }>;
		previousLeader: string | null;
	}

	let {
		currentIgt,
		replayElapsedMs,
		maxIgt,
		replayParticipants,
		skullEvents,
		nodePositions,
		nodeInfo,
		previousLeader
	}: Props = $props();

	// Compute player snapshots
	let snapshots: PlayerSnapshot[] = $derived.by(() => {
		const result: PlayerSnapshot[] = [];
		for (let i = 0; i < replayParticipants.length; i++) {
			const rp = replayParticipants[i];
			const phaseOffset = (i / replayParticipants.length) * Math.PI * 2;
			const snap = computePlayerPosition(
				rp,
				currentIgt,
				nodePositions,
				nodeInfo,
				phaseOffset,
				replayElapsedMs,
				i,
				replayParticipants.length
			);
			if (snap) result.push(snap);
		}
		return result;
	});

	// Leader
	let leaderId = $derived(computeLeader(snapshots));
	let leaderChanged = $derived(leaderId !== previousLeader && previousLeader !== null);

	// Node heat
	let nodeHeat = $derived(computeNodeHeat(skullEvents, currentIgt));

	// Active skulls: show skulls that are within SKULL_ANIM_MS of current replay time
	let activeSkulls = $derived.by(() => {
		const replayMs = igtToReplayMs(currentIgt, maxIgt);
		return skullEvents
			.filter((ev) => {
				const evReplayMs = igtToReplayMs(ev.igtMs, maxIgt);
				const age = replayMs - evReplayMs;
				return age >= 0 && age < REPLAY_DEFAULTS.SKULL_ANIM_MS;
			})
			.map((ev) => {
				const evReplayMs = igtToReplayMs(ev.igtMs, maxIgt);
				const age = replayMs - evReplayMs;
				const progress = age / REPLAY_DEFAULTS.SKULL_ANIM_MS;
				return { ...ev, progress };
			});
	});

	function heatOpacity(deaths: number): number {
		return Math.min(0.6, deaths * 0.08);
	}

	function skullScale(progress: number): number {
		// Overshoot in first 30%, then settle to 1.0, then hold
		if (progress < 0.3) {
			const t = progress / 0.3;
			return t * REPLAY_DEFAULTS.SKULL_PEAK_SCALE;
		}
		if (progress < 0.5) {
			const overshoot = REPLAY_DEFAULTS.SKULL_PEAK_SCALE - 1.0;
			return REPLAY_DEFAULTS.SKULL_PEAK_SCALE - ((progress - 0.3) / 0.2) * overshoot;
		}
		return 1.0;
	}

	function skullOpacity(progress: number): number {
		if (progress < 0.5) return 1;
		return 1 - (progress - 0.5) / 0.5;
	}
</script>

<!-- Node heat overlay -->
{#each [...nodeHeat.entries()] as [nodeId, deaths]}
	{@const pos = nodePositions.get(nodeId)}
	{#if pos}
		<circle
			cx={pos.x}
			cy={pos.y}
			r="16"
			fill="#EF4444"
			opacity={heatOpacity(deaths)}
			class="heat-glow"
		/>
	{/if}
{/each}

<!-- Player dots -->
{#each snapshots as snap (snap.participantId)}
	{@const rp = replayParticipants.find((r) => r.id === snap.participantId)}
	{#if rp}
		<circle
			cx={snap.x}
			cy={snap.y}
			r={RACER_DOT_RADIUS}
			fill={rp.color}
			class="replay-dot"
			filter="url(#replay-player-glow)"
		>
			<title>{rp.displayName}</title>
		</circle>
		<!-- Leader star -->
		{#if snap.participantId === leaderId}
			<text
				x={snap.x}
				y={snap.y - RACER_DOT_RADIUS - 5}
				text-anchor="middle"
				font-size="14"
				fill={leaderChanged ? '#FACC15' : '#C8A44E'}
				class="leader-star"
				class:flash={leaderChanged}
			>&#x2B51;</text>
		{/if}
	{/if}
{/each}

<!-- Skull animations -->
{#each activeSkulls as skull}
	{@const pos = nodePositions.get(skull.nodeId)}
	{#if pos}
		<text
			x={pos.x}
			y={pos.y}
			text-anchor="middle"
			dominant-baseline="central"
			font-size={18 * skullScale(skull.progress)}
			opacity={skullOpacity(skull.progress)}
			class="skull-anim"
		>&#x1F480;</text>
	{/if}
{/each}

<style>
	.replay-dot {
		pointer-events: none;
	}

	.heat-glow {
		pointer-events: none;
		filter: blur(8px);
	}

	.leader-star {
		pointer-events: none;
		transition: fill 0.3s ease;
	}

	.leader-star.flash {
		animation: star-flash 0.5s ease;
	}

	@keyframes star-flash {
		0%,
		100% {
			font-size: 14px;
		}
		50% {
			font-size: 20px;
		}
	}

	.skull-anim {
		pointer-events: none;
	}
</style>
