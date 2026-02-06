<script lang="ts">
	import { page } from '$app/state';
</script>

<div class="error-page">
	<span class="error-code">{page.status}</span>
	<h1 class="error-title">
		{#if page.status === 404}
			Lost in the fog
		{:else if page.status === 403}
			Sealed by fog gate
		{:else if page.status === 500}
			You died
		{:else}
			Something went wrong
		{/if}
	</h1>
	<p class="error-message">{page.error?.message}</p>
	<a href="/" class="btn btn-primary">Return to safety</a>
</div>

<style>
	.error-page {
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		min-height: 60vh;
		text-align: center;
		padding: 2rem;
		gap: 0.5rem;
	}

	.error-code {
		font-size: clamp(4rem, 12vw, 8rem);
		font-weight: 800;
		color: var(--color-gold);
		line-height: 1;
		opacity: 0.15;
	}

	.error-title {
		font-size: clamp(1.2rem, 3vw, 1.8rem);
		font-weight: 600;
		color: var(--color-text);
		margin: 0;
	}

	.error-message {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		margin: 0 0 1rem;
	}
</style>
