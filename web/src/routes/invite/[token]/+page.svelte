<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { acceptInvite, getTwitchLoginUrl } from '$lib/api';

	let { data } = $props();

	let invite = $derived(data.invite);
	let accepting = $state(false);
	let errorMessage = $state<string | null>(null);

	let isLoggedIn = $derived(auth.isLoggedIn);
	let isCorrectUser = $derived(
		auth.user?.twitch_username?.toLowerCase() === invite.twitch_username.toLowerCase()
	);

	function loginWithRedirect() {
		sessionStorage.setItem('redirect_after_login', window.location.pathname);
		window.location.href = getTwitchLoginUrl();
	}

	async function handleAccept() {
		accepting = true;
		errorMessage = null;
		try {
			const result = await acceptInvite(invite.token);
			goto(`/race/${result.race_id}`);
		} catch (e) {
			errorMessage = e instanceof Error ? e.message : 'Failed to accept invite';
			accepting = false;
		}
	}
</script>

<svelte:head>
	<title>Invite to {invite.race_name} - SpeedFog Racing</title>
</svelte:head>

<main>
	<div class="invite-card">
		<h1>Race Invite</h1>
		<div class="invite-details">
			<div class="detail">
				<span class="label">Race</span>
				<span class="value">{invite.race_name}</span>
			</div>
			<div class="detail">
				<span class="label">Organizer</span>
				<span class="value">{invite.organizer_name}</span>
			</div>
			<div class="detail">
				<span class="label">Status</span>
				<span class="badge badge-{invite.race_status}">{invite.race_status}</span>
			</div>
			<div class="detail">
				<span class="label">Invited as</span>
				<span class="value">{invite.twitch_username}</span>
			</div>
		</div>

		{#if errorMessage}
			<div class="error">{errorMessage}</div>
		{/if}

		<div class="actions">
			{#if !auth.initialized}
				<p class="hint">Loading...</p>
			{:else if !isLoggedIn}
				<p class="hint">Log in with Twitch to accept this invite.</p>
				<button class="btn btn-primary" onclick={loginWithRedirect}> Login with Twitch </button>
			{:else if isCorrectUser}
				<button class="btn btn-primary" onclick={handleAccept} disabled={accepting}>
					{accepting ? 'Accepting...' : 'Accept Invite'}
				</button>
			{:else}
				<div class="error">
					This invite is for <strong>{invite.twitch_username}</strong>, but you are logged in as
					<strong>{auth.user?.twitch_username}</strong>.
				</div>
			{/if}
		</div>
	</div>
</main>

<style>
	main {
		max-width: 600px;
		margin: 0 auto;
		padding: 2rem;
	}

	.invite-card {
		background: #16213e;
		border: 1px solid #0f3460;
		border-radius: 8px;
		padding: 2rem;
	}

	h1 {
		margin: 0 0 1.5rem 0;
		color: #9b59b6;
	}

	.invite-details {
		display: flex;
		flex-direction: column;
		gap: 1rem;
		margin-bottom: 1.5rem;
	}

	.detail {
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.label {
		color: #7f8c8d;
		font-size: 0.9rem;
		text-transform: uppercase;
	}

	.value {
		font-weight: 500;
	}

	.actions {
		display: flex;
		flex-direction: column;
		align-items: center;
		gap: 1rem;
	}

	.hint {
		color: #95a5a6;
		font-style: italic;
		margin: 0;
	}

	.error {
		background: #c0392b33;
		border: 1px solid #c0392b;
		color: #e74c3c;
		padding: 0.75rem 1rem;
		border-radius: 4px;
		margin-bottom: 1rem;
	}
</style>
