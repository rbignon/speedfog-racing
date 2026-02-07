<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { PLAYER_COLORS } from '$lib/dag/constants';

	interface Props {
		participants: WsParticipant[];
	}

	let { participants }: Props = $props();

	let finishers = $derived(participants.filter((p) => p.status === 'finished').slice(0, 3));

	const MEDALS = ['🥇', '🥈', '🥉'];

	function formatIgt(ms: number): string {
		const totalSeconds = Math.floor(ms / 1000);
		const hours = Math.floor(totalSeconds / 3600);
		const minutes = Math.floor((totalSeconds % 3600) / 60);
		const seconds = totalSeconds % 60;
		if (hours > 0) {
			return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
		}
		return `${minutes}:${seconds.toString().padStart(2, '0')}`;
	}

	function playerColor(p: WsParticipant): string {
		return PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
	}

	// Visual order: [2nd, 1st, 3rd] for classic podium layout
	let podiumOrder = $derived.by(() => {
		if (finishers.length < 2) return finishers.map((f, i) => ({ finisher: f, place: i }));
		const order: { finisher: WsParticipant; place: number }[] = [];
		if (finishers.length >= 2) order.push({ finisher: finishers[1], place: 1 });
		order.push({ finisher: finishers[0], place: 0 });
		if (finishers.length >= 3) order.push({ finisher: finishers[2], place: 2 });
		return order;
	});

	const HEIGHTS = [160, 120, 100];
</script>

{#if finishers.length > 0}
	<div class="podium">
		{#each podiumOrder as { finisher, place } (finisher.id)}
			<div class="podium-column" style="--bar-height: {HEIGHTS[place]}px;">
				<span class="medal">{MEDALS[place]}</span>
				<span class="podium-name">
					{finisher.twitch_display_name || finisher.twitch_username}
				</span>
				<span class="podium-time">{formatIgt(finisher.igt_ms)}</span>
				{#if finisher.death_count > 0}
					<span class="podium-deaths">💀 {finisher.death_count}</span>
				{/if}
				<div class="podium-bar" style="background: {playerColor(finisher)};">
					<span class="podium-place">{place + 1}</span>
				</div>
			</div>
		{/each}
	</div>
{/if}

<style>
	.podium {
		display: flex;
		align-items: flex-end;
		justify-content: center;
		gap: 0.5rem;
		max-width: 500px;
		margin: 0 auto;
		padding: 1.5rem 1rem 0;
	}

	.podium-column {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 0.25rem;
		flex: 1;
		min-width: 0;
	}

	.medal {
		font-size: 1.5rem;
	}

	.podium-name {
		font-weight: 600;
		font-size: var(--font-size-sm);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		max-width: 100%;
		text-align: center;
	}

	.podium-time {
		font-size: var(--font-size-sm);
		color: var(--color-success);
		font-variant-numeric: tabular-nums;
		font-weight: 500;
	}

	.podium-deaths {
		font-size: var(--font-size-sm);
		color: var(--color-danger, #ef4444);
	}

	.podium-bar {
		width: 100%;
		height: var(--bar-height);
		border-radius: var(--radius-sm) var(--radius-sm) 0 0;
		display: flex;
		align-items: flex-start;
		justify-content: center;
		padding-top: 0.5rem;
		opacity: 0.85;
	}

	.podium-place {
		font-size: var(--font-size-lg);
		font-weight: 700;
		color: var(--color-surface, #1a1a2e);
	}
</style>
