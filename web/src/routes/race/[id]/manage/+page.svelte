<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import {
		addParticipant,
		removeParticipant,
		generateSeedPacks,
		startRace,
		fetchRace,
		type RaceDetail,
		type DownloadInfo
	} from '$lib/api';

	let { data } = $props();
	let race: RaceDetail = $state(data.race);

	let authorized = $state(false);
	let authChecked = $state(false);
	let newUsername = $state('');
	let addingParticipant = $state(false);
	let generatingSeedPacks = $state(false);
	let startingRace = $state(false);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let downloads = $state<DownloadInfo[]>([]);
	let scheduledStart = $state('');

	$effect(() => {
		if (auth.initialized && !authChecked) {
			authChecked = true;
			if (!auth.user || auth.user.id !== race.organizer.id) {
				goto(`/race/${race.id}`);
			} else {
				authorized = true;
			}
		}
	});

	onMount(() => {
		// Set default scheduled start to 5 minutes from now
		const defaultStart = new Date(Date.now() + 5 * 60 * 1000);
		scheduledStart = defaultStart.toISOString().slice(0, 16);
	});

	async function handleAddParticipant(e: Event) {
		e.preventDefault();
		if (!newUsername.trim()) return;

		addingParticipant = true;
		error = null;
		success = null;

		try {
			const result = await addParticipant(race.id, newUsername.trim());
			if (result.participant) {
				success = `Added ${newUsername} as participant.`;
			} else if (result.invite) {
				success = `Invite created for ${newUsername}. They need to login to join.`;
			}
			newUsername = '';
			// Refresh race data
			race = await fetchRace(race.id);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to add participant.';
		} finally {
			addingParticipant = false;
		}
	}

	async function handleRemoveParticipant(participantId: string, username: string) {
		if (!confirm(`Remove ${username} from this race?`)) return;

		error = null;
		success = null;

		try {
			await removeParticipant(race.id, participantId);
			success = `Removed ${username}.`;
			// Refresh race data
			race = await fetchRace(race.id);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to remove participant.';
		}
	}

	async function handleGenerateSeedPacks() {
		if (race.participants.length === 0) {
			error = 'Add participants first.';
			return;
		}

		generatingSeedPacks = true;
		error = null;
		success = null;

		try {
			const result = await generateSeedPacks(race.id);
			downloads = result.downloads;
			success = `Generated ${downloads.length} seed pack(s).`;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to generate seed packs.';
		} finally {
			generatingSeedPacks = false;
		}
	}

	async function handleStartRace() {
		if (!scheduledStart) {
			error = 'Please select a start time.';
			return;
		}

		startingRace = true;
		error = null;
		success = null;

		try {
			const startDate = new Date(scheduledStart);
			await startRace(race.id, startDate);
			// Refresh race data to get full details
			race = await fetchRace(race.id);
			success = 'Race started! Status changed to countdown.';
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to start race.';
		} finally {
			startingRace = false;
		}
	}

	function canStartRace(): boolean {
		return race.status === 'draft' || race.status === 'open';
	}
</script>

<svelte:head>
	<title>Manage: {race.name} - SpeedFog Racing</title>
</svelte:head>

{#if !authorized}
	<main>
		<p class="loading">Checking authorization...</p>
	</main>
{:else}
	<main>
		<header>
			<h1>Manage: {race.name}</h1>
			<a href="/race/{race.id}" class="btn btn-secondary">← Back to Race</a>
		</header>

		{#if error}
			<div class="message error">{error}</div>
		{/if}
		{#if success}
			<div class="message success">{success}</div>
		{/if}

		<section class="section">
			<h2>Add Participant</h2>
			<form onsubmit={handleAddParticipant} class="add-form">
				<input
					type="text"
					bind:value={newUsername}
					placeholder="Twitch username"
					disabled={addingParticipant}
				/>
				<button type="submit" class="btn btn-primary" disabled={addingParticipant}>
					{addingParticipant ? 'Adding...' : 'Add'}
				</button>
			</form>
		</section>

		<section class="section">
			<h2>Participants ({race.participants.length})</h2>
			{#if race.participants.length === 0}
				<p class="empty">No participants yet. Add some above.</p>
			{:else}
				<ul class="participant-list">
					{#each race.participants as participant}
						<li class="participant-item">
							<div class="participant-info">
								{#if participant.user.twitch_avatar_url}
									<img src={participant.user.twitch_avatar_url} alt="" class="avatar" />
								{/if}
								<span>
									{participant.user.twitch_display_name || participant.user.twitch_username}
								</span>
								<span class="badge badge-{participant.status}">{participant.status}</span>
							</div>
							<button
								class="btn btn-danger btn-small"
								onclick={() =>
									handleRemoveParticipant(participant.id, participant.user.twitch_username)}
							>
								Remove
							</button>
						</li>
					{/each}
				</ul>
			{/if}
		</section>

		<section class="section">
			<h2>Generate Seed Packs</h2>
			<p class="hint">Generate personalized seed packs for all participants.</p>
			<button
				class="btn btn-primary"
				onclick={handleGenerateSeedPacks}
				disabled={generatingSeedPacks || race.participants.length === 0}
			>
				{generatingSeedPacks ? 'Generating...' : 'Generate Seed Packs'}
			</button>

			{#if downloads.length > 0}
				<div class="downloads">
					<h3>Download Links</h3>
					<ul>
						{#each downloads as download}
							<li>
								<a href={download.url} target="_blank">{download.twitch_username}.zip</a>
							</li>
						{/each}
					</ul>
				</div>
			{/if}
		</section>

		<section class="section">
			<h2>Start Race</h2>
			{#if canStartRace()}
				<p class="hint">Set the countdown start time for the race.</p>
				<div class="start-form">
					<input type="datetime-local" bind:value={scheduledStart} disabled={startingRace} />
					<button class="btn btn-primary" onclick={handleStartRace} disabled={startingRace}>
						{startingRace ? 'Starting...' : 'Start Race'}
					</button>
				</div>
			{:else}
				<p class="hint">
					Race is already in <strong>{race.status}</strong> status.
				</p>
			{/if}
		</section>
	</main>
{/if}

<style>
	main {
		max-width: 800px;
		margin: 0 auto;
		padding: 2rem;
	}

	header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 2rem;
	}

	h1 {
		margin: 0;
		color: var(--color-text);
		font-size: var(--font-size-2xl);
		font-weight: 600;
	}

	h2 {
		color: var(--color-gold);
		margin: 0 0 1rem 0;
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	h3 {
		font-size: 1rem;
		margin: 1rem 0 0.5rem 0;
	}

	.section {
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		padding: 1.5rem;
		margin-bottom: 1.5rem;
	}

	.message {
		padding: 1rem;
		border-radius: var(--radius-sm);
		margin-bottom: 1rem;
	}

	.message.error {
		background: var(--color-danger-dark);
		color: white;
	}

	.message.success {
		background: var(--color-success);
		color: white;
	}

	.add-form {
		display: flex;
		gap: 0.5rem;
	}

	.add-form input {
		flex: 1;
		padding: 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-bg);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: 1rem;
	}

	.add-form input:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	.participant-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.participant-item {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 0.75rem;
		background: var(--color-bg);
		border-radius: var(--radius-sm);
	}

	.participant-info {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
	}

	.btn-small {
		padding: 0.25rem 0.5rem;
		font-size: 0.85rem;
	}

	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.hint {
		color: var(--color-text-secondary);
		margin: 0 0 1rem 0;
		font-size: 0.9rem;
	}

	.downloads {
		margin-top: 1rem;
		padding-top: 1rem;
		border-top: 1px solid var(--color-border);
	}

	.downloads ul {
		list-style: none;
		padding: 0;
		margin: 0;
	}

	.downloads li {
		padding: 0.25rem 0;
	}

	.start-form {
		display: flex;
		gap: 0.5rem;
		align-items: center;
	}

	.start-form input {
		padding: 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-bg);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: 1rem;
	}

	.start-form input:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}
</style>
