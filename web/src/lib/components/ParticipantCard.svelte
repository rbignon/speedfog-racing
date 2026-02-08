<script lang="ts">
	import type { Participant } from '$lib/api';

	interface Props {
		participant: Participant;
		liveStatus?: string;
		isOrganizer?: boolean;
		isCurrentUser?: boolean;
		canRemove?: boolean;
		onRemove?: () => void;
		canDownload?: boolean;
		downloading?: boolean;
		onDownload?: () => void;
		downloadError?: string | null;
	}

	let {
		participant,
		liveStatus,
		isOrganizer = false,
		isCurrentUser = false,
		canRemove = false,
		onRemove,
		canDownload = false,
		downloading = false,
		onDownload,
		downloadError = null
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
			<span class="name-text">
				{participant.user.twitch_display_name || participant.user.twitch_username}
			</span>
			{#if isCurrentUser}
				<span class="you-badge">You</span>
			{/if}
		</span>
		<span class="status-text">{effectiveStatus}</span>
	</div>
	{#if isOrganizer}
		<span class="organizer-badge">Org</span>
	{/if}
	{#if canRemove}
		<button class="remove-btn" onclick={onRemove} title="Remove participant">&times;</button>
	{/if}
	{#if isCurrentUser && canDownload}
		<button
			class="download-btn"
			onclick={onDownload}
			disabled={downloading}
			title="Download Race Package"
			aria-label={downloading ? 'Downloading race package' : 'Download Race Package'}
		>
			{#if downloading}
				<svg class="spinner" viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
					<circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="2" stroke-dasharray="28" stroke-dashoffset="8" />
				</svg>
			{:else}
				<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
					<path d="M8 1v9m0 0L5 7m3 3 3-3M3 13h10" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" fill="none" />
				</svg>
			{/if}
		</button>
	{/if}
	{#if isCurrentUser && downloadError}
		<span class="download-error">{downloadError}</span>
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

	.download-btn {
		background: none;
		border: 1px solid var(--color-purple);
		color: var(--color-purple);
		border-radius: var(--radius-sm);
		cursor: pointer;
		padding: 0.3rem;
		line-height: 1;
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all var(--transition);
	}

	.download-btn:hover:not(:disabled) {
		background: rgba(139, 92, 246, 0.15);
		color: var(--color-purple-hover);
		border-color: var(--color-purple-hover);
	}

	.download-btn:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}

	.spinner {
		animation: spin 1s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	.download-error {
		color: var(--color-danger);
		font-size: var(--font-size-xs);
		padding: 0.15rem 0.75rem 0;
	}
</style>
