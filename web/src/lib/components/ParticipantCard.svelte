<script lang="ts">
	import type { Participant } from '$lib/api';
	import LiveBadge from './LiveBadge.svelte';

	interface Props {
		participant: Participant;
		liveStatus?: string;
		isOrganizer?: boolean;
		isCurrentUser?: boolean;
		isLive?: boolean;
		streamUrl?: string | null;
		canRemove?: boolean;
		onRemove?: () => void;
	}

	let {
		participant,
		liveStatus,
		isOrganizer = false,
		isCurrentUser = false,
		isLive = false,
		streamUrl = null,
		canRemove = false,
		onRemove
	}: Props = $props();

	let effectiveStatus = $derived(liveStatus ?? participant.status);
</script>

<div class="participant-card" class:current-user={isCurrentUser}>
	<span class="status-dot" class:ready={effectiveStatus === 'ready'}></span>
	{#if participant.user.twitch_avatar_url}
		<img src={participant.user.twitch_avatar_url} alt="" class="avatar" />
	{:else}
		<div class="avatar-placeholder"></div>
	{/if}
	<div class="info">
		<span class="name">
			<a href="/user/{participant.user.twitch_username}" class="name-text name-link">
				{participant.user.twitch_display_name || participant.user.twitch_username}
			</a>
			{#if isCurrentUser}
				<span class="you-badge">You</span>
			{/if}
		</span>
		<span class="status-text">{effectiveStatus}</span>
	</div>
	{#if isLive}
		<LiveBadge
			href={streamUrl ?? `https://twitch.tv/${participant.user.twitch_username}`}
			onclick={(e) => e.stopPropagation()}
		/>
	{/if}
	{#if isOrganizer}
		<span class="organizer-badge">Org</span>
	{/if}
	{#if canRemove}
		<button class="remove-btn" onclick={onRemove} title="Remove participant">&times;</button>
	{/if}
</div>

<style>
	.participant-card {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem;
		background: var(--color-bg);
		border-radius: var(--radius-sm);
	}

	.participant-card.current-user {
		border-left: 3px solid var(--color-purple);
		background: rgba(139, 92, 246, 0.06);
	}

	.status-dot {
		width: 8px;
		height: 8px;
		border-radius: 50%;
		background: var(--color-text-disabled);
		flex-shrink: 0;
	}

	.status-dot.ready {
		background: var(--color-success);
		box-shadow: 0 0 4px var(--color-success);
	}

	.avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.avatar-placeholder {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		background: var(--color-border);
		flex-shrink: 0;
	}

	.info {
		flex: 1;
		min-width: 0;
	}

	.name {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		min-width: 0;
	}

	.name-text {
		overflow: hidden;
		text-overflow: ellipsis;
		min-width: 0;
	}

	.name-link {
		color: inherit;
		text-decoration: none;
	}

	.name-link:hover {
		color: var(--color-purple);
	}

	.you-badge {
		padding: 0.1rem 0.35rem;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background: rgba(139, 92, 246, 0.15);
		color: var(--color-purple);
		flex-shrink: 0;
	}

	.status-text {
		display: block;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: capitalize;
	}

	.organizer-badge {
		padding: 0.15rem 0.4rem;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		background: rgba(200, 164, 78, 0.15);
		color: var(--color-gold);
		flex-shrink: 0;
	}

	.remove-btn {
		background: none;
		border: none;
		color: var(--color-text-disabled);
		font-size: 1.2rem;
		cursor: pointer;
		padding: 0 0.25rem;
		line-height: 1;
		flex-shrink: 0;
	}

	.remove-btn:hover {
		color: var(--color-danger);
	}
</style>
