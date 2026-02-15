<script lang="ts">
	import { raceStore } from '$lib/stores/race.svelte';
	import { MetroDagBlurred, MetroDagResults } from '$lib/dag';

	let { data } = $props();

	let raceStatus = $derived(raceStore.race?.status ?? data.race.status);
	let liveSeed = $derived(raceStore.seed);
	let totalLayers = $derived(liveSeed?.total_layers ?? data.race.seed_total_layers);
	let totalNodes = $derived(liveSeed?.total_nodes ?? data.race.seed_total_nodes);
	let totalPaths = $derived(liveSeed?.total_paths ?? data.race.seed_total_paths);

	$effect(() => {
		raceStore.connect(data.race.id);
		return () => {
			raceStore.disconnect();
		};
	});
</script>

<div class="dag-overlay">
	{#if liveSeed?.graph_json && (raceStatus === 'running' || raceStatus === 'finished')}
		<MetroDagResults graphJson={liveSeed.graph_json} participants={raceStore.leaderboard} />
	{:else if totalNodes && totalPaths && totalLayers}
		<MetroDagBlurred {totalLayers} {totalNodes} {totalPaths} />
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
