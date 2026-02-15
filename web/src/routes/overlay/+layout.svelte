<script lang="ts">
	import '../../app.css';
	import { onMount } from 'svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import { site } from '$lib/stores/site.svelte';

	let { children } = $props();

	onMount(() => {
		auth.init();
		site.init();
	});
</script>

<div class="overlay-root">
	{@render children()}
</div>

<style>
	:global(html),
	:global(body) {
		background: transparent !important;
		margin: 0;
		padding: 0;
		overflow: hidden;
	}

	.overlay-root {
		width: 100vw;
		height: 100vh;
		background: transparent;
		overflow: hidden;
	}
</style>
