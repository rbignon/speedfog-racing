<script lang="ts">
	import type { PendingInvite } from '$lib/api';

	interface Props {
		invite: PendingInvite;
		canRemove?: boolean;
		onRemove?: () => void;
	}

	let { invite, canRemove = false, onRemove }: Props = $props();
</script>

<div class="invite-card">
	<div class="avatar-placeholder">
		<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
			<path
				d="M8 8a3 3 0 1 0 0-6 3 3 0 0 0 0 6zm0 2c-3.3 0-6 1.3-6 3v1h12v-1c0-1.7-2.7-3-6-3z"
				fill="currentColor"
				opacity="0.4"
			/>
		</svg>
	</div>
	<div class="info">
		<span class="name">{invite.twitch_username}</span>
		<span class="status-text">Invited</span>
	</div>
	{#if canRemove}
		<button class="remove-btn" onclick={onRemove} title="Revoke invite">&times;</button>
	{/if}
</div>

<style>
	.invite-card {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem;
		background: var(--color-bg);
		border-radius: var(--radius-sm);
		border-left: 3px dashed var(--color-border);
	}

	.avatar-placeholder {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		background: var(--color-border);
		flex-shrink: 0;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-text-disabled);
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
		color: var(--color-text-disabled);
		font-style: italic;
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
