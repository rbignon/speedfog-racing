<script lang="ts">
	import { untrack } from 'svelte';
	import { page } from '$app/state';
	import { auth } from '$lib/stores/auth.svelte';
	import { trainingStore } from '$lib/stores/training.svelte';
	import { getEffectiveLocale } from '$lib/stores/locale.svelte';
	import { MetroDagFull } from '$lib/dag';

	let { data } = $props();

	let liveRace = $derived(trainingStore.race);
	let liveSeed = $derived(trainingStore.seed);
	let liveParticipant = $derived(trainingStore.participant);

	let sessionStatus = $derived(liveRace?.status ?? data.session.status);
	let graphJson = $derived(liveSeed?.graph_json ?? data.session.graph_json ?? null);

	let dagParticipants = $derived.by(() => {
		if (liveParticipant) return [liveParticipant];
		if (!data.session.progress_nodes || data.session.progress_nodes.length === 0) return [];
		return [
			{
				id: data.session.id,
				twitch_username: data.session.user?.twitch_username ?? '',
				twitch_display_name: data.session.user?.twitch_display_name ?? null,
				status: data.session.status === 'active' ? ('playing' as const) : data.session.status,
				current_zone:
					data.session.progress_nodes[data.session.progress_nodes.length - 1]?.node_id ?? null,
				current_layer: data.session.current_layer ?? 0,
				igt_ms: data.session.igt_ms,
				death_count: data.session.death_count,
				color_index: 0,
				mod_connected: false,
				zone_history: data.session.progress_nodes
			}
		];
	});

	let follow = $derived(page.url.searchParams.get('follow') === 'true');
	let maxLayers = $derived(
		(() => {
			const raw = page.url.searchParams.get('maxLayers');
			if (raw === null || raw === '') return 5;
			const n = parseInt(raw, 10);
			return isNaN(n) || n < 3 ? 5 : n;
		})()
	);
	let labelFontSize = $derived(
		(() => {
			const raw = page.url.searchParams.get('fontSize');
			if (raw === null || raw === '') return undefined;
			const n = parseInt(raw, 10);
			return isNaN(n) || n < 6 || n > 32 ? undefined : n;
		})()
	);

	$effect(() => {
		if (!auth.initialized) return;

		const locale = untrack(() => getEffectiveLocale());
		trainingStore.connect(data.session.id, locale);
		return () => {
			trainingStore.disconnect();
		};
	});
</script>

<div class="dag-overlay">
	{#if graphJson && dagParticipants.length > 0}
		<MetroDagFull
			{graphJson}
			participants={dagParticipants}
			raceStatus={sessionStatus === 'active' ? 'running' : sessionStatus}
			transparent
			{follow}
			{maxLayers}
			{labelFontSize}
			showLiveDots
			fullPathOpacity
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
