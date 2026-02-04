<script lang="ts">
	import { onMount } from 'svelte';
	import { initAuth, currentUser, isLoggedIn, isLoading, logout } from '$lib/stores/auth';
	import { getTwitchLoginUrl } from '$lib/api';

	let { children } = $props();

	onMount(() => {
		initAuth();
	});
</script>

<div class="app">
	<header>
		<div class="header-content">
			<a href="/" class="logo">SpeedFog Racing</a>
			<nav>
				{#if $isLoading}
					<span class="loading">Loading...</span>
				{:else if $isLoggedIn}
					<span class="user-info">
						{#if $currentUser?.twitch_avatar_url}
							<img src={$currentUser.twitch_avatar_url} alt="" class="avatar" />
						{/if}
						<span>{$currentUser?.twitch_display_name || $currentUser?.twitch_username}</span>
					</span>
					<a href="/race/new" class="btn btn-primary">Create Race</a>
					<button onclick={() => logout()} class="btn btn-secondary">Logout</button>
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
		font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, sans-serif;
		display: flex;
		flex-direction: column;
	}

	:global(body) {
		margin: 0;
		padding: 0;
		background-color: #1a1a2e;
		color: #eee;
	}

	:global(a) {
		color: #9b59b6;
	}

	:global(a:hover) {
		color: #8e44ad;
	}

	:global(.btn) {
		padding: 0.5rem 1rem;
		border: none;
		border-radius: 4px;
		cursor: pointer;
		text-decoration: none;
		font-size: 0.9rem;
		display: inline-block;
	}

	:global(.btn-primary) {
		background: #9b59b6;
		color: white;
	}

	:global(.btn-primary:hover) {
		background: #8e44ad;
	}

	:global(.btn-secondary) {
		background: #34495e;
		color: white;
	}

	:global(.btn-secondary:hover) {
		background: #2c3e50;
	}

	:global(.btn-twitch) {
		background: #6441a5;
		color: white;
	}

	:global(.btn-twitch:hover) {
		background: #563d7c;
	}

	:global(.btn-danger) {
		background: #c0392b;
		color: white;
	}

	:global(.btn-danger:hover) {
		background: #a93226;
	}

	:global(.badge) {
		padding: 0.25rem 0.5rem;
		border-radius: 4px;
		font-size: 0.75rem;
		text-transform: uppercase;
	}

	:global(.badge-draft) {
		background: #7f8c8d;
		color: white;
	}

	:global(.badge-open) {
		background: #27ae60;
		color: white;
	}

	:global(.badge-countdown) {
		background: #f39c12;
		color: white;
	}

	:global(.badge-running) {
		background: #e74c3c;
		color: white;
	}

	:global(.badge-finished) {
		background: #3498db;
		color: white;
	}

	/* Participant status badges */
	:global(.badge-registered) {
		background: #95a5a6;
		color: white;
	}

	:global(.badge-ready) {
		background: #27ae60;
		color: white;
	}

	:global(.badge-playing) {
		background: #f39c12;
		color: white;
	}

	:global(.badge-abandoned) {
		background: #e74c3c;
		color: white;
	}

	header {
		background: #16213e;
		padding: 1rem 2rem;
		border-bottom: 1px solid #0f3460;
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
		font-size: 1.5rem;
		font-weight: bold;
		color: #9b59b6;
		text-decoration: none;
	}

	.logo:hover {
		color: #8e44ad;
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
	}

	.loading {
		color: #7f8c8d;
		font-style: italic;
	}

	.content {
		flex: 1;
	}
</style>
