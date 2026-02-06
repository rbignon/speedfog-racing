<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import { getTwitchLoginUrl } from '$lib/api';

	let { children } = $props();

	onMount(() => {
		auth.init();
	});
</script>

<div class="app">
	<header>
		<div class="header-content">
			<a href="/" class="logo">SpeedFog Racing</a>
			<nav>
				{#if auth.loading}
					<span class="loading">Loading...</span>
				{:else if auth.isLoggedIn}
					<span class="user-info">
						{#if auth.user?.twitch_avatar_url}
							<img src={auth.user.twitch_avatar_url} alt="" class="avatar" />
						{/if}
						<span>{auth.user?.twitch_display_name || auth.user?.twitch_username}</span>
					</span>
					<a href="/race/new" class="btn btn-primary">Create Race</a>
					<button onclick={() => auth.logout()} class="btn btn-secondary">Logout</button>
				{:else}
					<a href={getTwitchLoginUrl()} class="btn btn-twitch">Login with Twitch</a>
				{/if}
			</nav>
		</div>
	</header>

	<div class="content">
		{@render children()}
	</div>
</div>

<style>
	.app {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
	}

	header {
		background: var(--color-bg);
		padding: 1rem 2rem;
		border-bottom: 1px solid var(--color-border);
	}

	.header-content {
		max-width: 1200px;
		margin: 0 auto;
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.logo {
		margin: 0;
		font-size: var(--font-size-xl);
		font-weight: 700;
		color: var(--color-gold);
		text-decoration: none;
	}

	.logo:hover {
		color: var(--color-gold-hover);
	}

	nav {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.user-info {
		display: flex;
		align-items: center;
		gap: 0.5rem;
	}

	.avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 2px solid var(--color-border);
	}

	.loading {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.content {
		flex: 1;
	}
</style>
