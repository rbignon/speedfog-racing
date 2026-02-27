<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { raceStore } from '$lib/stores/race.svelte';
	import { getEffectiveLocale } from '$lib/stores/locale.svelte';
	import { MetroDagBlurred, MetroDagFull } from '$lib/dag';

	let { data } = $props();

	let raceStatus = $derived(raceStore.race?.status ?? data.race.status);
	let liveSeed = $derived(raceStore.seed);
	let totalLayers = $derived(liveSeed?.total_layers ?? data.race.seed_total_layers);
	let totalNodes = $derived(liveSeed?.total_nodes ?? data.race.seed_total_nodes);
	let totalPaths = $derived(liveSeed?.total_paths ?? data.race.seed_total_paths);
	let follow = $derived(page.url.searchParams.get('follow') === 'true');

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
			showLiveDots
		/>
	{:else if totalNodes && totalPaths && totalLayers}
		<MetroDagBlurred {totalLayers} {totalNodes} {totalPaths} transparent />
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
