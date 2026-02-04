<script lang="ts">
	import { currentUser } from '$lib/stores/auth';
	import type { RaceDetail, Participant } from '$lib/api';

	let { data } = $props();
	let race: RaceDetail = $derived(data.race);

	function isOrganizer(): boolean {
		return $currentUser?.id === race.organizer.id;
	}

	function isParticipant(): boolean {
		if (!$currentUser) return false;
		return race.participants.some((p) => p.user.id === $currentUser?.id);
	}

	function formatIgt(ms: number): string {
		const totalSeconds = Math.floor(ms / 1000);
		const hours = Math.floor(totalSeconds / 3600);
		const minutes = Math.floor((totalSeconds % 3600) / 60);
		const seconds = totalSeconds % 60;
		if (hours > 0) {
			return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
		}
		return `${minutes}:${seconds.toString().padStart(2, '0')}`;
	}

	function formatDate(dateStr: string): string {
		return new Date(dateStr).toLocaleString();
	}

	function getSortedParticipants(): Participant[] {
		return [...race.participants].sort((a, b) => {
			// Finished players first, sorted by finish time (igt_ms)
			if (a.status === 'finished' && b.status !== 'finished') return -1;
			if (b.status === 'finished' && a.status !== 'finished') return 1;
			if (a.status === 'finished' && b.status === 'finished') {
				return a.igt_ms - b.igt_ms;
			}
			// Then by layer (higher = better)
			if (a.current_layer !== b.current_layer) {
				return b.current_layer - a.current_layer;
			}
			// Then by IGT (lower = better)
			return a.igt_ms - b.igt_ms;
		});
	}
</script>

<svelte:head>
	<title>{race.name} - SpeedFog Racing</title>
</svelte:head>

<div class="race-page">
	<aside class="sidebar">
		<h2>Leaderboard</h2>
		{#if race.participants.length === 0}
			<p class="empty">No participants yet</p>
		{:else}
			<ol class="leaderboard">
				{#each getSortedParticipants() as participant, index}
					<li class="participant" class:finished={participant.status === 'finished'}>
						<span class="rank">{index + 1}</span>
						<div class="participant-info">
							<span class="name">
								{participant.user.twitch_display_name || participant.user.twitch_username}
							</span>
							<span class="stats">
								Layer {participant.current_layer}
								{#if race.seed_total_layers}/ {race.seed_total_layers}{/if}
								• {formatIgt(participant.igt_ms)}
							</span>
						</div>
						{#if participant.status === 'finished'}
							<span class="finished-badge">✓</span>
						{/if}
					</li>
				{/each}
			</ol>
		{/if}
	</aside>

	<main class="main-content">
		<header class="race-header">
			<div>
				<h1>{race.name}</h1>
				<p class="organizer">
					Organized by {race.organizer.twitch_display_name || race.organizer.twitch_username}
				</p>
			</div>
			<span class="badge badge-{race.status}">{race.status}</span>
		</header>

		<div class="dag-placeholder">
			<div class="dag-content">
				<span class="dag-icon">🗺️</span>
				<p>DAG Visualization</p>
				<p class="dag-note">Coming in Phase 2</p>
			</div>
		</div>

		<div class="race-info">
			<div class="info-grid">
				<div class="info-item">
					<span class="label">Seed</span>
					<span class="value">{race.seed_total_layers || '?'} layers</span>
				</div>
				<div class="info-item">
					<span class="label">Pool</span>
					<span class="value">{race.pool_name || 'standard'}</span>
				</div>
				<div class="info-item">
					<span class="label">Participants</span>
					<span class="value">{race.participant_count}</span>
				</div>
				<div class="info-item">
					<span class="label">Created</span>
					<span class="value">{formatDate(race.created_at)}</span>
				</div>
				{#if race.scheduled_start}
					<div class="info-item">
						<span class="label">Scheduled Start</span>
						<span class="value">{formatDate(race.scheduled_start)}</span>
					</div>
				{/if}
			</div>

			<div class="actions">
				{#if isOrganizer()}
					<a href="/race/{race.id}/manage" class="btn btn-primary">Manage Race</a>
				{/if}
				{#if isParticipant() && !isOrganizer()}
					<span class="participant-note">You are participating in this race</span>
				{/if}
			</div>
		</div>
	</main>
</div>

<style>
	.race-page {
		display: flex;
		min-height: calc(100vh - 60px);
	}

	.sidebar {
		width: 280px;
		background: #16213e;
		border-right: 1px solid #0f3460;
		padding: 1.5rem;
		flex-shrink: 0;
	}

	.sidebar h2 {
		color: #9b59b6;
		margin: 0 0 1rem 0;
		font-size: 1.1rem;
	}

	.leaderboard {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.participant {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem;
		background: #1a1a2e;
		border-radius: 4px;
		border: 1px solid #0f3460;
	}

	.participant.finished {
		border-color: #27ae60;
	}

	.rank {
		width: 24px;
		height: 24px;
		background: #0f3460;
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: 0.8rem;
		font-weight: bold;
		flex-shrink: 0;
	}

	.participant-info {
		flex: 1;
		min-width: 0;
	}

	.name {
		display: block;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.stats {
		display: block;
		font-size: 0.8rem;
		color: #7f8c8d;
	}

	.finished-badge {
		color: #27ae60;
		font-size: 1.2rem;
	}

	.empty {
		color: #7f8c8d;
		font-style: italic;
	}

	.main-content {
		flex: 1;
		padding: 2rem;
		display: flex;
		flex-direction: column;
		gap: 1.5rem;
	}

	.race-header {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
	}

	.race-header h1 {
		margin: 0;
		color: #eee;
	}

	.organizer {
		margin: 0.25rem 0 0 0;
		color: #7f8c8d;
	}

	.dag-placeholder {
		flex: 1;
		min-height: 300px;
		background: #16213e;
		border: 2px dashed #0f3460;
		border-radius: 8px;
		display: flex;
		align-items: center;
		justify-content: center;
	}

	.dag-content {
		text-align: center;
		color: #7f8c8d;
	}

	.dag-icon {
		font-size: 3rem;
		display: block;
		margin-bottom: 0.5rem;
	}

	.dag-content p {
		margin: 0.25rem 0;
	}

	.dag-note {
		font-size: 0.85rem;
		font-style: italic;
	}

	.race-info {
		background: #16213e;
		border-radius: 8px;
		padding: 1.5rem;
	}

	.info-grid {
		display: grid;
		grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
		gap: 1rem;
		margin-bottom: 1.5rem;
	}

	.info-item {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
	}

	.label {
		font-size: 0.8rem;
		color: #7f8c8d;
		text-transform: uppercase;
	}

	.value {
		font-weight: 500;
	}

	.actions {
		display: flex;
		gap: 1rem;
		align-items: center;
	}

	.participant-note {
		color: #27ae60;
		font-style: italic;
	}
</style>
