<script lang="ts">
	let { children } = $props();
</script>

<div class="overlay-root">
	{@render children()}
</div>

<style>
	:global(body) {
		background: transparent !important;
		overflow: hidden;
	}

	.overlay-root {
		width: 100vw;
		height: 100vh;
		background: transparent;
		overflow: hidden;
	}
</style>
