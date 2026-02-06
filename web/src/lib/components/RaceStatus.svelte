<script lang="ts">
	interface Props {
		status: string;
		scheduledStart?: string | null;
	}

	let { status, scheduledStart = null }: Props = $props();

	let countdown = $state<string | null>(null);

	function updateCountdown() {
		if (!scheduledStart || status !== 'countdown') {
			countdown = null;
			return;
		}

		const now = Date.now();
		const start = new Date(scheduledStart).getTime();
		const diff = start - now;

		if (diff <= 0) {
			countdown = 'Starting...';
			return;
		}

		const seconds = Math.floor(diff / 1000);
		const minutes = Math.floor(seconds / 60);
		const remainingSeconds = seconds % 60;

		if (minutes > 0) {
			countdown = `${minutes}:${remainingSeconds.toString().padStart(2, '0')}`;
		} else {
			countdown = `${remainingSeconds}s`;
		}
	}

	$effect(() => {
		updateCountdown();
		const interval = setInterval(updateCountdown, 1000);
		return () => clearInterval(interval);
	});

	function getStatusLabel(s: string): string {
		switch (s) {
			case 'draft':
				return 'Draft';
			case 'open':
				return 'Open';
			case 'countdown':
				return 'Starting';
			case 'running':
				return 'Live';
			case 'finished':
				return 'Finished';
			default:
				return s;
		}
	}
</script>

<div class="race-status">
	<span class="badge badge-{status}">{getStatusLabel(status)}</span>
	{#if countdown}
		<span class="countdown">{countdown}</span>
	{/if}
</div>

<style>
	.race-status {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.countdown {
		font-size: 1.5rem;
		font-weight: bold;
		font-variant-numeric: tabular-nums;
		color: #f39c12;
	}
</style>
