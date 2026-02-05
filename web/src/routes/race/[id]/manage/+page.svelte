<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import { currentUser, isInitialized } from '$lib/stores/auth';
	import { get } from 'svelte/store';
	import {
		addParticipant,
		removeParticipant,
		generateZips,
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
	let generatingZips = $state(false);
	let startingRace = $state(false);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let downloads = $state<DownloadInfo[]>([]);
	let scheduledStart = $state('');

	$effect(() => {
		if (get(isInitialized) && !authChecked) {
			authChecked = true;
			const user = get(currentUser);
			if (!user || user.id !== race.organizer.id) {
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

	async function handleGenerateZips() {
		if (race.participants.length === 0) {
			error = 'Add participants first.';
			return;
		}

		generatingZips = true;
		error = null;
		success = null;

		try {
			const result = await generateZips(race.id);
			downloads = result.downloads;
			success = `Generated ${downloads.length} zip file(s).`;
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to generate zips.';
		} finally {
			generatingZips = false;
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
			<h2>Generate Zips</h2>
			<p class="hint">Generate personalized mod zips for all participants.</p>
			<button
				class="btn btn-primary"
				onclick={handleGenerateZips}
				disabled={generatingZips || race.participants.length === 0}
			>
				{generatingZips ? 'Generating...' : 'Generate Zips'}
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
		color: #9b59b6;
	}

	h2 {
		color: #9b59b6;
		margin: 0 0 1rem 0;
		font-size: 1.1rem;
	}

	h3 {
		font-size: 1rem;
		margin: 1rem 0 0.5rem 0;
	}

	.section {
		background: #16213e;
		border-radius: 8px;
		padding: 1.5rem;
		margin-bottom: 1.5rem;
	}

	.message {
		padding: 1rem;
		border-radius: 4px;
		margin-bottom: 1rem;
	}

	.message.error {
		background: #c0392b;
		color: white;
	}

	.message.success {
		background: #27ae60;
		color: white;
	}

	.add-form {
		display: flex;
		gap: 0.5rem;
	}

	.add-form input {
		flex: 1;
		padding: 0.75rem;
		border: 1px solid #0f3460;
		border-radius: 4px;
		background: #1a1a2e;
		color: #eee;
		font-size: 1rem;
	}

	.add-form input:focus {
		outline: none;
		border-color: #9b59b6;
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
		background: #1a1a2e;
		border-radius: 4px;
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
		color: #7f8c8d;
		font-style: italic;
	}

	.hint {
		color: #7f8c8d;
		margin: 0 0 1rem 0;
		font-size: 0.9rem;
	}

	.downloads {
		margin-top: 1rem;
		padding-top: 1rem;
		border-top: 1px solid #0f3460;
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
		border: 1px solid #0f3460;
		border-radius: 4px;
		background: #1a1a2e;
		color: #eee;
		font-size: 1rem;
	}

	.start-form input:focus {
		outline: none;
		border-color: #9b59b6;
	}

	.loading {
		color: #7f8c8d;
		font-style: italic;
	}
</style>
