<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';

	interface Props {
		participants: WsParticipant[];
	}

	let { participants }: Props = $props();

	let finishers = $derived(participants.filter((p) => p.status === 'finished'));

	let winnerTime = $derived.by(() => {
		if (finishers.length === 0) return null;
		return Math.min(...finishers.map((p) => p.igt_ms));
	});

	let slowestTime = $derived.by(() => {
		if (finishers.length === 0) return null;
		return Math.max(...finishers.map((p) => p.igt_ms));
	});

	let avgDeaths = $derived.by(() => {
		if (participants.length === 0) return 0;
		const total = participants.reduce((sum, p) => sum + p.death_count, 0);
		return Math.round((total / participants.length) * 10) / 10;
	});

	let finisherCount = $derived(`${finishers.length} / ${participants.length}`);

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
</script>

<div class="race-stats">
	<div class="info-grid">
		{#if winnerTime !== null}
			<div class="info-item">
				<span class="label">Winner Time</span>
				<span class="value">{formatIgt(winnerTime)}</span>
			</div>
		{/if}
		{#if slowestTime !== null && finishers.length > 1}
			<div class="info-item">
				<span class="label">Slowest Time</span>
				<span class="value">{formatIgt(slowestTime)}</span>
			</div>
		{/if}
		<div class="info-item">
			<span class="label">Avg Deaths</span>
			<span class="value">{avgDeaths}</span>
		</div>
		<div class="info-item">
			<span class="label">Finishers</span>
			<span class="value">{finisherCount}</span>
		</div>
	</div>
</div>

<style>
	.race-stats {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 1.5rem;
	}

	.info-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(120px, 1fr));
		gap: 1rem;
	}

	.info-item {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.label {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 500;
	}

	.value {
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}
</style>
