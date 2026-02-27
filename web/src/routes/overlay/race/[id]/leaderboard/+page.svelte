<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { raceStore } from '$lib/stores/race.svelte';
	import { getEffectiveLocale } from '$lib/stores/locale.svelte';
	import LeaderboardOverlay from '$lib/components/LeaderboardOverlay.svelte';

	let { data } = $props();

	let raceStatus = $derived(raceStore.race?.status ?? data.race.status);
	let liveSeed = $derived(raceStore.seed);
	let totalLayers = $derived(liveSeed?.total_layers ?? data.race.seed_total_layers);
	let mode = $derived<'running' | 'finished'>(raceStatus === 'finished' ? 'finished' : 'running');

	let lines = $derived(
		(() => {
			const raw = page.url.searchParams.get('lines');
			if (raw === null || raw === '') return null;
			const n = parseInt(raw, 10);
			return isNaN(n) || n <= 0 ? null : n;
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

<div class="leaderboard-overlay">
	<LeaderboardOverlay participants={raceStore.leaderboard} {totalLayers} {mode} {lines} />
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
