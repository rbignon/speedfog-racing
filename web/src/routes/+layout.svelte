<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import { site } from '$lib/stores/site.svelte';
	import { getTwitchLoginUrl } from '$lib/api';

	let { children } = $props();

	onMount(() => {
		auth.init();
		site.init();
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
				{:else if !site.initialized}
					<!-- Wait for site config -->
				{:else if site.comingSoon}
					<span class="btn btn-twitch btn-disabled">Login with Twitch</span>
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
		border-bottom: 1px solid var(--color-border);
		height: 74px;
	}

	.header-content {
		display: flex;
		justify-content: space-between;
		align-items: center;
		padding: 1rem 2rem 1rem 1.5rem;
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

	@media (max-width: 480px) {
		.header-content {
			padding: 0.75rem 1rem;
		}

		.logo {
			font-size: var(--font-size-lg);
			white-space: nowrap;
		}

		nav {
			gap: 0.5rem;
		}

		nav :global(.btn) {
			font-size: var(--font-size-sm);
			padding: 0.4rem 0.75rem;
		}
	}
</style>
