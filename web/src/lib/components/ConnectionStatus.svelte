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
		border-radius: 4px;
	}

	.connected {
		background: rgba(39, 174, 96, 0.2);
		color: #27ae60;
	}

	.disconnected {
		background: rgba(243, 156, 18, 0.2);
		color: #f39c12;
	}

	.indicator {
		width: 8px;
		height: 8px;
		border-radius: 50%;
	}

	.connected .indicator {
		background: #27ae60;
		box-shadow: 0 0 4px #27ae60;
	}

	.disconnected .indicator {
		background: #f39c12;
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
