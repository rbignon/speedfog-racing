<script lang="ts">
	import '../app.css';
	import { onMount } from 'svelte';
	import { auth } from '$lib/stores/auth.svelte';
	import { site } from '$lib/stores/site.svelte';
	import { goto } from '$app/navigation';
	import { page } from '$app/state';
	import { getTwitchLoginUrl } from '$lib/api';

	let { children } = $props();

	let isOverlay = $derived(page.url.pathname.startsWith('/overlay/'));
	let isRaceDetailPage = $derived(page.route.id === '/race/[id]');

	let userMenuOpen = $state(false);
	let userMenuEl: HTMLDivElement | undefined = $state();

	function toggleUserMenu() {
		userMenuOpen = !userMenuOpen;
	}

	function closeUserMenu() {
		userMenuOpen = false;
	}

	function handleWindowClick(e: MouseEvent) {
		if (userMenuOpen && userMenuEl && !userMenuEl.contains(e.target as Node)) {
			closeUserMenu();
		}
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape' && userMenuOpen) {
			closeUserMenu();
		}
	}

	onMount(() => {
		auth.init();
		site.init();
	});
</script>

<svelte:window onclick={handleWindowClick} onkeydown={handleKeydown} />

{#if isOverlay}
	{@render children()}
{:else}
	<div class="app" class:app-fixed={isRaceDetailPage}>
		<header>
			<div class="header-content">
				<a href={auth.isLoggedIn ? '/dashboard' : '/'} class="logo">SpeedFog Racing<span class="beta-badge">Beta</span></a>
				<nav>
					<a href="/help" class="help-icon" aria-label="Help">?</a>
					{#if auth.loading}
						<span class="loading">Loading...</span>
					{:else if auth.isLoggedIn}
						<a href="/races" class="btn btn-secondary">Races</a>
						<a href="/training" class="btn btn-secondary">Training</a>
						{#if auth.isAdmin}
							<a href="/admin" class="btn btn-secondary">Admin</a>
						{/if}
						{#if auth.canCreateRace}
							<a href="/race/new" class="btn btn-primary">Create Race</a>
						{/if}
						<div class="user-menu" bind:this={userMenuEl}>
							<button class="user-menu-trigger" onclick={toggleUserMenu}>
								{#if auth.user?.twitch_avatar_url}
									<img src={auth.user.twitch_avatar_url} alt="" class="avatar" />
								{/if}
								<span class="user-menu-name">{auth.user?.twitch_display_name || auth.user?.twitch_username}</span>
								<span class="chevron">&#9662;</span>
							</button>
							{#if userMenuOpen}
								<div class="user-dropdown">
									<a href="/dashboard" class="dropdown-item" onclick={closeUserMenu}>Dashboard</a>
									<a href="/user/{auth.user?.twitch_username}" class="dropdown-item" onclick={closeUserMenu}>Profile</a>
									<a href="/settings" class="dropdown-item" onclick={closeUserMenu}>Settings</a>
									<hr class="dropdown-divider" />
									<button class="dropdown-item" onclick={() => { closeUserMenu(); auth.logout(); goto('/'); }}>Logout</button>
								</div>
							{/if}
						</div>
					{:else if !site.initialized}
						<!-- Wait for site config -->
					{:else if site.comingSoon}
						<span class="btn btn-twitch btn-disabled">Login with Twitch</span>
					{:else}
						<a href={getTwitchLoginUrl()} class="btn btn-twitch" data-sveltekit-reload>Login with Twitch</a>
					{/if}
				</nav>
			</div>
		</header>

		<div class="content">
			{@render children()}
		</div>

		{#if !isRaceDetailPage}
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
						<a href="/help">Help</a>
						<a
							href="https://discord.gg/Qmw67J3mR9"
							target="_blank"
							rel="noopener noreferrer">Discord</a
						>
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
					</nav>
				</div>
			</footer>
		{/if}
	</div>
{/if}

<style>
	.app {
		min-height: 100vh;
		display: flex;
		flex-direction: column;
		overflow-x: hidden;
	}

	.app-fixed {
		height: 100vh;
		overflow: hidden;
	}

	.app-fixed .content {
		overflow-y: hidden;
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

	.beta-badge {
		font-size: 0.4em;
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background: var(--color-gold);
		color: var(--color-bg);
		padding: 0.1em 0.4em;
		border-radius: 4px;
		margin-left: 0.4em;
		vertical-align: super;
	}

	nav {
		display: flex;
		align-items: center;
		gap: 1rem;
	}

	.help-icon {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 28px;
		height: 28px;
		border-radius: 50%;
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		text-decoration: none;
		font-size: var(--font-size-sm);
		font-weight: 600;
		flex-shrink: 0;
		transition: all var(--transition);
	}

	.help-icon:hover {
		border-color: var(--color-purple);
		color: var(--color-purple);
	}

	.user-menu {
		position: relative;
	}

	.user-menu-trigger {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		background: none;
		border: none;
		color: inherit;
		cursor: pointer;
		padding: 0;
		font-family: var(--font-family);
		font-size: var(--font-size-base);
	}

	.user-menu-trigger:hover {
		color: var(--color-purple);
	}

	.chevron {
		font-size: 0.7em;
		color: var(--color-text-secondary);
	}

	.avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 2px solid var(--color-border);
	}

	.user-dropdown {
		position: absolute;
		top: 100%;
		right: 0;
		margin-top: 0.5rem;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		min-width: 160px;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
		z-index: 100;
	}

	.dropdown-item {
		display: block;
		width: 100%;
		padding: 0.6rem 1rem;
		background: none;
		border: none;
		color: var(--color-text);
		text-decoration: none;
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		text-align: left;
		cursor: pointer;
		transition: background var(--transition);
	}

	.dropdown-item:hover {
		background: var(--color-bg);
	}

	.dropdown-divider {
		margin: 0;
		border: none;
		border-top: 1px solid var(--color-border);
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
		min-width: 0;
		overflow-y: auto;
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

	@media (max-width: 768px) {
		.app-fixed {
			height: auto;
			overflow: visible;
		}

		.app-fixed .content {
			overflow-y: auto;
		}
	}

	@media (max-width: 640px) {
		.header-content {
			padding: 0.75rem 1rem;
			flex-wrap: wrap;
			gap: 0.5rem;
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

		.user-menu-name {
			display: none;
		}

		.chevron {
			display: none;
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
