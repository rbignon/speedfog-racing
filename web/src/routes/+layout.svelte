<script lang="ts">
	import { onMount } from 'svelte';
	import { initAuth } from '$lib/stores/auth';

	let { children } = $props();

	onMount(() => {
		initAuth();
	});
</script>

<div class="app">
	{@render children()}
</div>

<style>
	.app {
		min-height: 100vh;
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
	}

	:global(body) {
		margin: 0;
		padding: 0;
		background-color: #1a1a2e;
		color: #eee;
	}

	:global(a) {
		color: #9b59b6;
	}

	:global(a:hover) {
		color: #8e44ad;
	}
</style>
