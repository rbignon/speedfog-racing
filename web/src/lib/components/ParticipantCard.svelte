<script lang="ts">
	import type { Participant } from '$lib/api';

	interface Props {
		participant: Participant;
		liveStatus?: string;
		isOrganizer?: boolean;
		canRemove?: boolean;
		onRemove?: () => void;
	}

	let {
		participant,
		liveStatus,
		isOrganizer = false,
		canRemove = false,
		onRemove
	}: Props = $props();

	let effectiveStatus = $derived(liveStatus ?? participant.status);
</script>

<div class="participant-card">
	<span class="status-dot" class:ready={effectiveStatus === 'ready'}></span>
	{#if participant.user.twitch_avatar_url}
		<img src={participant.user.twitch_avatar_url} alt="" class="avatar" />
	{:else}
		<div class="avatar-placeholder"></div>
	{/if}
	<div class="info">
		<span class="name">
			{participant.user.twitch_display_name || participant.user.twitch_username}
		</span>
		<span class="status-text">{effectiveStatus}</span>
	</div>
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
		display: block;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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
