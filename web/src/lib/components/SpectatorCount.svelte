<script lang="ts">
	interface Props {
		count: number;
	}

	let { count }: Props = $props();
</script>

<div class="spectator-count">
	<svg
		class="eye-icon"
		width="16"
		height="16"
		viewBox="0 0 24 24"
		fill="none"
		stroke="currentColor"
		stroke-width="2"
		stroke-linecap="round"
		stroke-linejoin="round"
	>
		<path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z" />
		<circle cx="12" cy="12" r="3" />
	</svg>
	<span>{count} watching</span>
</div>

<style>
	.spectator-count {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
	}

	.eye-icon {
		flex-shrink: 0;
	}
</style>
