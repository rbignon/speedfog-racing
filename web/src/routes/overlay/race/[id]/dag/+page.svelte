<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { raceStore } from '$lib/stores/race.svelte';
	import { getEffectiveLocale } from '$lib/stores/locale.svelte';
	import { MetroDagFull } from '$lib/dag';

	let { data } = $props();

	let raceStatus = $derived(raceStore.race?.status ?? data.race.status);
	let liveSeed = $derived(raceStore.seed);
	let follow = $derived(page.url.searchParams.get('follow') === 'true');
	let maxLayers = $derived(
		(() => {
			const raw = page.url.searchParams.get('maxLayers');
			if (raw === null || raw === '') return 5;
			const n = parseInt(raw, 10);
			return isNaN(n) || n < 3 ? 5 : n;
		})()
	);

	$effect(() => {
		if (!auth.initialized) return;

		const locale = untrack(() => getEffectiveLocale());
		raceStore.connect(data.race.id, locale);
		return () => {
			raceStore.disconnect();
		};
	});
</script>

<div class="dag-overlay">
	{#if liveSeed?.graph_json && (raceStatus === 'running' || raceStatus === 'finished')}
		<MetroDagFull
			graphJson={liveSeed.graph_json}
			participants={raceStore.leaderboard}
			{raceStatus}
			transparent
			{follow}
			{maxLayers}
			showLiveDots
		/>
	{:else if liveSeed?.graph_json && raceStatus === 'setup'}
		<MetroDagFull
			graphJson={liveSeed.graph_json}
			participants={raceStore.leaderboard}
			raceStatus="setup"
			transparent
			hideLabels
			{follow}
			{maxLayers}
			showLiveDots
		/>
	{/if}
</div>

<style>
	.dag-overlay {
		width: 100%;
		height: 100vh;
		display: flex;
		align-items: center;
		justify-content: center;
	}
</style>
