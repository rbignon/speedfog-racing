<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import {
		removeParticipant,
		removeCaster,
		generateSeedPacks,
		startRace,
		fetchRace,
		type RaceDetail,
		type DownloadInfo
	} from '$lib/api';
	import ParticipantSearch from '$lib/components/ParticipantSearch.svelte';
	import RaceStatus from '$lib/components/RaceStatus.svelte';

	let { data } = $props();
	let race: RaceDetail = $state(data.race);

	let authorized = $state(false);
	let authChecked = $state(false);
	let generatingSeedPacks = $state(false);
	let startingRace = $state(false);
	let error = $state<string | null>(null);
	let success = $state<string | null>(null);
	let downloads = $state<DownloadInfo[]>([]);
	let showCasterSearch = $state(false);
	let showParticipantSearch = $state(false);

	let isDraftOrOpen = $derived(race.status === 'draft' || race.status === 'open');

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

	async function handleRemoveParticipant(participantId: string, username: string) {
		if (!confirm(`Remove ${username} from this race?`)) return;

		error = null;
		success = null;

		try {
			await removeParticipant(race.id, participantId);
			success = `Removed ${username}.`;
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
		startingRace = true;
		error = null;
		success = null;

		try {
			await startRace(race.id);
			race = await fetchRace(race.id);
			success = 'Race started!';
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to start race.';
		} finally {
			startingRace = false;
		}
	}

	async function handleRemoveCaster(casterId: string, username: string) {
		if (!confirm(`Remove caster ${username}?`)) return;

		error = null;
		success = null;

		try {
			await removeCaster(race.id, casterId);
			success = `Removed caster ${username}.`;
			race = await fetchRace(race.id);
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to remove caster.';
		}
	}

	async function handleCasterAdded() {
		showCasterSearch = false;
		race = await fetchRace(race.id);
		success = 'Caster added.';
	}

	async function handleParticipantAdded() {
		showParticipantSearch = false;
		race = await fetchRace(race.id);
		success = 'Participant added.';
	}

	function isOrganizer(userId: string): boolean {
		return userId === race.organizer.id;
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
			<div class="header-left">
				<h1>Manage: {race.name}</h1>
				<div class="header-meta">
					<RaceStatus status={race.status} />
					{#if race.pool_name}
						<span class="pool-badge">{race.pool_name}</span>
					{/if}
				</div>
			</div>
			<a href="/race/{race.id}" class="btn btn-secondary">← Back to Race</a>
		</header>

		{#if error}
			<div class="message error">{error}</div>
		{/if}
		{#if success}
			<div class="message success">{success}</div>
		{/if}

		<section class="section">
			<h2>Participants ({race.participants.length})</h2>
			{#if race.participants.length === 0}
				<p class="empty">No participants yet.</p>
			{:else}
				<ul class="participant-list">
					{#each race.participants as participant (participant.id)}
						<li class="participant-item">
							<div class="participant-info">
								{#if participant.user.twitch_avatar_url}
									<img src={participant.user.twitch_avatar_url} alt="" class="avatar" />
								{/if}
								<span>
									{participant.user.twitch_display_name || participant.user.twitch_username}
								</span>
								<span class="badge badge-{participant.status}">{participant.status}</span>
								{#if isOrganizer(participant.user.id)}
									<span class="organizer-tag">organizer</span>
								{/if}
							</div>
							{#if isDraftOrOpen && !isOrganizer(participant.user.id)}
								<button
									class="btn btn-danger btn-small"
									onclick={() =>
										handleRemoveParticipant(
											participant.id,
											participant.user.twitch_username
										)}
								>
									Remove
								</button>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}

			{#if isDraftOrOpen}
				{#if showParticipantSearch}
					<div class="search-row">
						<ParticipantSearch
							mode="participant"
							raceId={race.id}
							onAdded={handleParticipantAdded}
							onCancel={() => (showParticipantSearch = false)}
						/>
					</div>
				{:else}
					<button
						class="btn btn-secondary"
						style="margin-top: 0.75rem"
						onclick={() => (showParticipantSearch = true)}
					>
						+ Add Participant
					</button>
				{/if}
			{/if}
		</section>

		<section class="section">
			<h2>Casters ({race.casters.length})</h2>
			{#if race.casters.length === 0}
				<p class="empty">No casters yet.</p>
			{:else}
				<ul class="participant-list">
					{#each race.casters as caster (caster.id)}
						<li class="participant-item">
							<div class="participant-info">
								{#if caster.user.twitch_avatar_url}
									<img src={caster.user.twitch_avatar_url} alt="" class="avatar" />
								{/if}
								<span>
									{caster.user.twitch_display_name || caster.user.twitch_username}
								</span>
							</div>
							<button
								class="btn btn-danger btn-small"
								onclick={() =>
									handleRemoveCaster(caster.id, caster.user.twitch_username)}
							>
								Remove
							</button>
						</li>
					{/each}
				</ul>
			{/if}

			{#if showCasterSearch}
				<div class="search-row">
					<ParticipantSearch
						mode="caster"
						raceId={race.id}
						onAdded={handleCasterAdded}
						onCancel={() => (showCasterSearch = false)}
					/>
				</div>
			{:else}
				<button
					class="btn btn-secondary"
					style="margin-top: 0.75rem"
					onclick={() => (showCasterSearch = true)}
				>
					+ Add Caster
				</button>
			{/if}
		</section>

		{#if isDraftOrOpen}
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
									<a href={download.url} target="_blank"
										>{download.twitch_username}.zip</a
									>
								</li>
							{/each}
						</ul>
					</div>
				{/if}
			</section>

			<section class="section">
				<h2>Start Race</h2>
				<button
					class="btn btn-primary"
					onclick={handleStartRace}
					disabled={startingRace}
				>
					{startingRace ? 'Starting...' : 'Start Race'}
				</button>
			</section>
		{:else}
			<section class="section">
				<p class="hint">
					Race is <strong>{race.status}</strong> — management actions are locked.
				</p>
			</section>
		{/if}
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
		align-items: flex-start;
		margin-bottom: 2rem;
		gap: 1rem;
	}

	.header-left {
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.header-meta {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.pool-badge {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		background: var(--color-surface);
		padding: 0.15rem 0.5rem;
		border-radius: var(--radius-sm);
		text-transform: capitalize;
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

	.organizer-tag {
		font-size: var(--font-size-xs);
		color: var(--color-gold);
		background: var(--color-surface);
		padding: 0.1rem 0.4rem;
		border-radius: var(--radius-sm);
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

	.search-row {
		margin-top: 0.75rem;
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

	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	@media (max-width: 640px) {
		main {
			padding: 1rem;
		}

		header {
			flex-direction: column;
			align-items: flex-start;
		}

		h1 {
			font-size: var(--font-size-xl);
		}

		.section {
			padding: 1rem;
		}

		.participant-item {
			flex-direction: column;
			align-items: flex-start;
			gap: 0.5rem;
		}
	}
</style>
