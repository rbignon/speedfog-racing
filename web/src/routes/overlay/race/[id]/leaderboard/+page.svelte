<script lang="ts">
	import { raceStore } from '$lib/stores/race.svelte';
	import LeaderboardOverlay from '$lib/components/LeaderboardOverlay.svelte';

	let { data } = $props();

	let raceStatus = $derived(raceStore.race?.status ?? data.race.status);
	let liveSeed = $derived(raceStore.seed);
	let totalLayers = $derived(liveSeed?.total_layers ?? data.race.seed_total_layers);
	let mode = $derived<'running' | 'finished'>(raceStatus === 'finished' ? 'finished' : 'running');

	$effect(() => {
		raceStore.connect(data.race.id);
		return () => {
			raceStore.disconnect();
		};
	});
</script>

<div class="leaderboard-overlay">
	<LeaderboardOverlay participants={raceStore.leaderboard} {totalLayers} {mode} />
</div>

<style>
	.leaderboard-overlay {
		width: 100%;
		height: 100vh;
		display: flex;
		flex-direction: column;
		justify-content: flex-start;
		padding: 1rem;
		box-sizing: border-box;
	}
</style>
