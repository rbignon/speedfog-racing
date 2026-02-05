<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';

	interface Props {
		participants: WsParticipant[];
		totalLayers?: number | null;
	}

	let { participants, totalLayers = null }: Props = $props();

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
	<h2>Leaderboard</h2>

	{#if participants.length === 0}
		<p class="empty">No participants yet</p>
	{:else}
		<ol class="list">
			{#each participants as participant, index (participant.id)}
				<li class="participant {getStatusClass(participant.status)}">
					<span class="rank">{index + 1}</span>
					<div class="info">
						<span class="name">
							{participant.twitch_display_name || participant.twitch_username}
						</span>
						<span class="stats">
							{#if participant.status === 'finished'}
								<span class="finished-time">{formatIgt(participant.igt_ms)}</span>
							{:else if participant.status === 'playing'}
								Layer {participant.current_layer}{totalLayers ? `/${totalLayers}` : ''}
								• {formatIgt(participant.igt_ms)}
							{:else}
								<span class="status-text">{participant.status}</span>
							{/if}
						</span>
					</div>
					{#if participant.status === 'finished'}
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
		color: #9b59b6;
		margin: 0 0 1rem 0;
		font-size: 1.1rem;
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
		background: #1a1a2e;
		border-radius: 4px;
		border: 1px solid #0f3460;
		transition: border-color 0.2s;
	}

	.participant.finished {
		border-color: #27ae60;
	}

	.participant.playing {
		border-color: #f39c12;
	}

	.participant.abandoned {
		opacity: 0.5;
	}

	.rank {
		width: 24px;
		height: 24px;
		background: #0f3460;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.8rem;
		font-weight: bold;
		flex-shrink: 0;
	}

	.participant.finished .rank {
		background: #27ae60;
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
		font-size: 0.8rem;
		color: #7f8c8d;
	}

	.finished-time {
		color: #27ae60;
		font-weight: 500;
	}

	.status-text {
		text-transform: capitalize;
	}

	.finish-icon {
		color: #27ae60;
		font-size: 1.2rem;
	}

	.empty {
		color: #7f8c8d;
		font-style: italic;
	}
</style>
