<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { PLAYER_COLORS } from '$lib/dag/constants';

	interface Props {
		participants: WsParticipant[];
		totalLayers?: number | null;
		mode?: 'running' | 'finished';
	}

	let { participants, totalLayers = null, mode = 'running' }: Props = $props();

	function playerColor(p: WsParticipant): string {
		return PLAYER_COLORS[p.color_index % PLAYER_COLORS.length];
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

	function displayName(p: WsParticipant): string {
		return p.twitch_display_name || p.twitch_username;
	}
</script>

<ol class="overlay-leaderboard">
	{#each participants as participant, index (participant.id)}
		{@const color = playerColor(participant)}
		<li class="row">
			<span class="rank">{index + 1}</span>
			<span class="dot" style="background: {color};"></span>
			<span class="name">{displayName(participant)}</span>
			<span class="stats">
				{#if participant.status === 'playing'}
					<span class="layer">{participant.current_layer}{totalLayers ? `/${totalLayers}` : ''}</span>
					{#if participant.death_count > 0}
						<span class="deaths">{participant.death_count}</span>
					{/if}
				{:else if participant.status === 'finished'}
					<span class="igt finished">{formatIgt(participant.igt_ms)}</span>
					{#if participant.death_count > 0}
						<span class="deaths">{participant.death_count}</span>
					{/if}
				{:else if participant.status === 'abandoned'}
					<span class="dnf">DNF</span>
				{:else}
					<span class="waiting">{participant.status}</span>
				{/if}
			</span>
		</li>
	{/each}
</ol>

<style>
	.overlay-leaderboard {
		list-style: none;
		padding: 0.5rem;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
	}

	.row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		color: white;
		font-size: 1rem;
		text-shadow:
			0 2px 4px rgba(0, 0, 0, 0.9),
			0 0 8px rgba(0, 0, 0, 0.7);
	}

	.rank {
		width: 1.5ch;
		text-align: right;
		flex-shrink: 0;
		opacity: 0.7;
		margin-right: 0.5em;
	}

	.dot {
		width: 12px;
		height: 12px;
		border-radius: 50%;
		flex-shrink: 0;
		box-shadow: 0 0 4px rgba(0, 0, 0, 0.5);
	}

	.name {
		flex: 1;
		min-width: 0;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
		font-weight: 600;
	}

	.stats {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		flex-shrink: 0;
		font-variant-numeric: tabular-nums;
	}

	.layer {
		font-weight: 600;
		opacity: 0.9;
	}

	.igt {
		opacity: 0.8;
	}

	.igt.finished {
		color: #4ade80;
		opacity: 1;
	}

	.deaths {
		color: #f87171;
		opacity: 0.9;
	}

	.deaths::before {
		content: '\1F480';
		margin-right: 0.15em;
	}

	.dnf {
		color: #9ca3af;
		font-style: italic;
	}

	.waiting {
		text-transform: capitalize;
		opacity: 0.6;
	}
</style>
