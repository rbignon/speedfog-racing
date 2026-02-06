<script lang="ts">
	interface Props {
		connected: boolean;
	}

	let { connected }: Props = $props();
</script>

<div class="connection-status" class:connected class:disconnected={!connected}>
	<span class="indicator"></span>
	<span class="label">{connected ? 'Live' : 'Reconnecting...'}</span>
</div>

<style>
	.connection-status {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		font-size: 0.85rem;
		padding: 0.25rem 0.5rem;
		border-radius: var(--radius-sm);
	}

	.connected {
		background: rgba(16, 185, 129, 0.15);
		color: var(--color-success);
	}

	.disconnected {
		background: rgba(200, 164, 78, 0.15);
		color: var(--color-warning);
	}

	.indicator {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.connected .indicator {
		background: var(--color-success);
		box-shadow: 0 0 4px var(--color-success);
	}

	.disconnected .indicator {
		background: var(--color-warning);
		animation: pulse 1s infinite;
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
		}
		50% {
			opacity: 0.5;
		}
	}

	.label {
		font-weight: 500;
	}
</style>
