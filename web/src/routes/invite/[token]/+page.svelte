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
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 2rem;
	}

	h1 {
		margin: 0 0 1.5rem 0;
		color: var(--color-text);
		font-size: var(--font-size-2xl);
		font-weight: 600;
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
		color: var(--color-text-secondary);
		font-size: 0.9rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 500;
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
		color: var(--color-text-secondary);
		font-style: italic;
		margin: 0;
	}

	.error {
		background: rgba(220, 38, 38, 0.15);
		border: 1px solid var(--color-danger-dark);
		color: var(--color-danger);
		padding: 0.75rem 1rem;
		border-radius: var(--radius-sm);
		margin-bottom: 1rem;
	}

	@media (max-width: 640px) {
		main {
			padding: 1rem;
		}

		.invite-card {
			padding: 1.25rem;
		}
	}
</style>
