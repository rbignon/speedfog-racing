<script lang="ts">
	let { dotOnly = false }: { dotOnly?: boolean } = $props();
</script>

<span class="live-indicator">
	<span class="live-dot"></span>
	{#if !dotOnly}
		<span class="live-text">LIVE</span>
	{/if}
</span>

<style>
	.live-indicator {
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}

	.live-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--color-danger, #ef4444);
		animation: pulse 1.5s ease-in-out infinite;
	}

	.live-text {
		font-size: var(--font-size-xs, 0.75rem);
		font-weight: 700;
		color: var(--color-danger, #ef4444);
		letter-spacing: 0.05em;
		text-transform: uppercase;
	}

	@keyframes pulse {
		0%,
		100% {
			opacity: 1;
			transform: scale(1);
		}
		50% {
			opacity: 0.5;
			transform: scale(0.85);
		}
	}

	@media (prefers-reduced-motion: reduce) {
		.live-dot {
			animation: none;
		}
	}
</style>
