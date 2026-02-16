<script lang="ts">
	import type { User } from '$lib/api';

	interface Props {
		user: User;
		showAvatar?: boolean;
	}

	let { user, showAvatar = false }: Props = $props();

	let displayName = $derived(user.twitch_display_name || user.twitch_username);
</script>

<a href="/user/{user.twitch_username}" class="user-link">
	{#if showAvatar && user.twitch_avatar_url}
		<img src={user.twitch_avatar_url} alt="" class="user-link-avatar" />
	{/if}
	{displayName}
</a>

<style>
	.user-link {
		color: inherit;
		text-decoration: none;
		display: inline-flex;
		align-items: center;
		gap: 0.35rem;
	}

	.user-link:hover {
		color: var(--color-purple);
		text-decoration: underline;
	}

	.user-link-avatar {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		object-fit: cover;
	}
</style>
