<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { PLAYER_COLORS } from '$lib/dag/constants';

	interface Props {
		participants: WsParticipant[];
		totalLayers?: number | null;
		mode?: 'running' | 'finished';
	}

	let { participants, totalLayers = null, mode = 'running' }: Props = $props();

	const MEDALS = ['🥇', '🥈', '🥉'];

	function rankColor(participant: WsParticipant): string | null {
		if (participant.status !== 'playing' && participant.status !== 'finished') return null;
		return PLAYER_COLORS[participant.color_index % PLAYER_COLORS.length];
	}

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

	function getStatusClass(status: string): string {
		switch (status) {
			case 'finished':
				return 'finished';
			case 'playing':
				return 'playing';
			case 'ready':
				return 'ready';
			case 'abandoned':
				return 'abandoned';
			default:
				return '';
		}
	}
</script>

<div class="leaderboard">
	<h2>{mode === 'finished' ? 'Results' : 'Leaderboard'}</h2>

	{#if participants.length === 0}
		<p class="empty">No participants yet</p>
	{:else}
		<ol class="list">
			{#each participants as participant, index (participant.id)}
				{@const color = rankColor(participant)}
				{@const medal =
					mode === 'finished' && participant.status === 'finished' && index < 3
						? MEDALS[index]
						: null}
				<li class="participant {getStatusClass(participant.status)}">
					{#if medal}
						<span class="medal">{medal}</span>
					{:else}
						<span class="rank" style={color ? `background: ${color}; color: #1a1a2e;` : ''}
							>{index + 1}</span
						>
					{/if}
					<div class="info">
						<span class="name">
							{participant.twitch_display_name || participant.twitch_username}
						</span>
						<span class="stats">
							{#if mode === 'finished' && participant.status === 'finished'}
								<span class="finished-time">{formatIgt(participant.igt_ms)}</span>
								{#if participant.death_count > 0}
									<span class="death-count">{participant.death_count}</span>
								{/if}
							{:else if mode === 'finished' && participant.status === 'abandoned'}
								<span class="dnf"
									>DNF (L{participant.current_layer}{totalLayers ? `/${totalLayers}` : ''})</span
								>
							{:else if participant.status === 'finished'}
								<span class="finished-time">{formatIgt(participant.igt_ms)}</span>
								{#if participant.death_count > 0}
									<span class="death-count">{participant.death_count}</span>
								{/if}
							{:else if participant.status === 'playing'}
								Layer {participant.current_layer}{totalLayers ? `/${totalLayers}` : ''}
								• {formatIgt(participant.igt_ms)}
								{#if participant.death_count > 0}
									<span class="death-count">{participant.death_count}</span>
								{/if}
							{:else}
								<span class="status-text">{participant.status}</span>
							{/if}
						</span>
					</div>
					{#if mode === 'running' && participant.status === 'finished'}
						<span class="finish-icon">✓</span>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
</div>

<style>
	.leaderboard {
		height: 100%;
		display: flex;
		flex-direction: column;
	}

	h2 {
		color: var(--color-gold);
		margin: 0 0 1rem 0;
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	.list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		overflow-y: auto;
		flex: 1;
	}

	.participant {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem;
		background: var(--color-bg);
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border);
		transition: border-color var(--transition);
	}

	.participant:hover {
		background: var(--color-surface-elevated);
	}

	.participant.finished {
		border-color: var(--color-success);
	}

	.participant.playing {
		border-color: var(--color-warning);
	}

	.participant.abandoned {
		opacity: 0.5;
	}

	.rank {
		width: 24px;
		height: 24px;
		background: var(--color-border);
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: var(--font-size-sm);
		font-weight: bold;
		flex-shrink: 0;
		color: var(--color-text-secondary);
	}

	.participant.finished .rank {
		background: var(--color-success);
		color: white;
	}

	.info {
		flex: 1;
		min-width: 0;
	}

	.name {
		display: block;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.stats {
		display: block;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	.finished-time {
		color: var(--color-success);
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}

	.status-text {
		text-transform: capitalize;
	}

	.finish-icon {
		color: var(--color-success);
		font-size: 1.2rem;
	}

	.death-count {
		color: var(--color-danger, #ef4444);
		font-size: var(--font-size-sm);
	}

	.death-count::before {
		content: '\1F480';
		margin-left: 0.25em;
	}

	.medal {
		width: 24px;
		height: 24px;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 1.2rem;
		flex-shrink: 0;
	}

	.dnf {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
	}
</style>
