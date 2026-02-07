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

	<footer>
		<div class="footer-content">
			<p class="footer-credit">
				Based on the <a
					href="https://www.nexusmods.com/eldenring/mods/3295"
					target="_blank"
					rel="noopener noreferrer">Fog Gate Randomizer</a
				> by thefifthmatt
			</p>
			<nav class="footer-links" aria-label="Footer navigation">
				<a href="/about">About</a>
				<a
					href="https://github.com/rbignon/speedfog"
					target="_blank"
					rel="noopener noreferrer">SpeedFog</a
				>
				<a
					href="https://github.com/rbignon/speedfog-racing"
					target="_blank"
					rel="noopener noreferrer">SpeedFog Racing</a
				>
				<a
					href="https://www.nexusmods.com/eldenring/mods/3295"
					target="_blank"
					rel="noopener noreferrer">Fog Gate Randomizer</a
				>
			</nav>
		</div>
	</footer>
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
		display: flex;
		flex-direction: column;
		min-height: 0;
	}

	footer {
		border-top: 1px solid var(--color-border);
		padding: 1.5rem 2rem;
		flex-shrink: 0;
	}

	.footer-content {
		max-width: 1200px;
		margin: 0 auto;
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 1rem;
	}

	.footer-credit {
		margin: 0;
		color: var(--color-text-disabled);
		font-size: var(--font-size-sm);
	}

	.footer-credit a {
		color: var(--color-text-secondary);
		text-decoration: none;
	}

	.footer-credit a:hover {
		color: var(--color-purple);
	}

	.footer-links {
		display: flex;
		gap: 1.5rem;
	}

	.footer-links a {
		color: var(--color-text-disabled);
		text-decoration: none;
		font-size: var(--font-size-sm);
		transition: color 0.2s ease;
	}

	.footer-links a:hover {
		color: var(--color-purple);
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

		footer {
			padding: 1.25rem 1rem;
		}

		.footer-content {
			flex-direction: column;
			text-align: center;
		}

		.footer-links {
			gap: 1rem;
			flex-wrap: wrap;
			justify-content: center;
		}
	}
</style>
