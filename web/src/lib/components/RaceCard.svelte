<script lang="ts">
	import type { Race, RaceStatus } from '$lib/api';
	import { goto } from '$app/navigation';
	import { timeAgo } from '$lib/utils/time';
	import LiveIndicator from './LiveIndicator.svelte';

	let {
		race,
		role,
		hideOrganizer = false,
		variant = 'default'
	}: {
		race: Race;
		role?: string;
		hideOrganizer?: boolean;
		variant?: 'default' | 'compact';
	} = $props();

	let isRunning = $derived(race.status === 'running');
	let displayName = $derived(race.organizer.twitch_display_name || race.organizer.twitch_username);
	let overflowCount = $derived(
		Math.max(0, race.participant_count - race.participant_previews.length)
	);

	function statusBorderClass(status: RaceStatus): string {
		switch (status) {
			case 'draft':
				return 'border-draft';
			case 'open':
				return 'border-open';
			case 'running':
				return 'border-running';
			case 'finished':
				return 'border-finished';
			default:
				return '';
		}
	}

	function actionLabel(status: RaceStatus, userRole?: string): string | null {
		if (status === 'running') return 'Watch →';
		if (status === 'finished') return 'Results →';
		if (userRole === 'Organizing' && status === 'draft') return 'Set up →';
		if (userRole === 'Organizing' && status === 'open') return 'Manage →';
		return null;
	}

	let action = $derived(actionLabel(race.status, role));
	let relativeTime = $derived(timeAgo(race.created_at));
</script>

<a
	href="/race/{race.id}"
	class="race-card {statusBorderClass(race.status)}"
	class:compact={variant === 'compact'}
>
	<div class="race-header">
		<div class="race-title">
			{#if isRunning}
				<LiveIndicator dotOnly />
			{/if}
			<span class="race-name">{race.name}</span>
		</div>
		<div class="race-badges">
			{#if role}
				<span class="badge badge-role">{role}</span>
			{/if}
			<span class="badge badge-{race.status}">{race.status}</span>
		</div>
	</div>

	{#if race.participant_previews.length > 0}
		<div class="avatar-row">
			<div class="avatar-stack">
				{#each race.participant_previews as user}
					{#if user.twitch_avatar_url}
						<img
							src={user.twitch_avatar_url}
							alt={user.twitch_display_name || user.twitch_username}
							class="avatar"
						/>
					{:else}
						<span class="avatar avatar-placeholder">
							{(user.twitch_display_name || user.twitch_username).charAt(0).toUpperCase()}
						</span>
					{/if}
				{/each}
				{#if overflowCount > 0}
					<span class="avatar avatar-overflow">+{overflowCount}</span>
				{/if}
			</div>
			<span class="relative-time">{relativeTime}</span>
		</div>
	{:else}
		<div class="avatar-row">
			<span class="no-participants">No players yet</span>
			<span class="relative-time">{relativeTime}</span>
		</div>
	{/if}

	<div class="race-meta">
		<span>
			{race.participant_count} player{race.participant_count !== 1 ? 's' : ''}
			{#if race.pool_name}
				&middot; {race.pool_name}
			{/if}
		</span>
		{#if action && hideOrganizer}
			<span class="action-label">{action}</span>
		{:else if !hideOrganizer}
			<span class="race-organizer">
				by
				{#if race.organizer.twitch_avatar_url}
					<img src={race.organizer.twitch_avatar_url} alt="" class="organizer-avatar" />
				{/if}
				<button
					class="organizer-link"
					onclick={(e) => {
						e.preventDefault();
						e.stopPropagation();
						goto(`/user/${race.organizer.twitch_username}`);
					}}
				>
					{displayName}
				</button>
			</span>
		{/if}
	</div>
</a>

<style>
	.race-card {
		display: block;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 1rem 1.25rem;
		text-decoration: none;
		color: inherit;
		transition:
			border-color var(--transition),
			box-shadow var(--transition);
	}

	.race-card:hover {
		border-color: var(--color-purple);
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
	}

	.race-card.compact {
		padding: 0.75rem 1rem;
	}

	/* Status left-border accents */
	.border-draft {
		border-left: 3px solid var(--color-text-disabled);
	}

	.border-open {
		border-left: 3px solid var(--color-success);
	}

	.border-running {
		border-left: 3px solid var(--color-gold);
	}

	.border-finished {
		border-left: 3px solid var(--color-info);
	}

	/* Header row */
	.race-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
	}

	.race-title {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		min-width: 0;
	}

	.race-name {
		font-size: 1.05rem;
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.race-badges {
		display: flex;
		gap: 0.4rem;
		flex-shrink: 0;
	}

	.badge-role {
		background: rgba(107, 114, 128, 0.2);
		color: var(--color-text-secondary);
	}

	/* Avatar row */
	.avatar-row {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.5rem;
	}

	.avatar-stack {
		display: flex;
		align-items: center;
	}

	.avatar {
		width: 26px;
		height: 26px;
		border-radius: 50%;
		border: 2px solid var(--color-surface);
		margin-left: -6px;
		object-fit: cover;
	}

	.avatar:first-child {
		margin-left: 0;
	}

	.avatar-placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--color-surface-elevated);
		color: var(--color-text-secondary);
		font-size: var(--font-size-xs);
		font-weight: 600;
	}

	.avatar-overflow {
		display: flex;
		align-items: center;
		justify-content: center;
		background: var(--color-surface-elevated);
		color: var(--color-text-secondary);
		font-size: var(--font-size-xs);
		font-weight: 600;
	}

	.no-participants {
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.relative-time {
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
	}

	/* Meta row */
	.race-meta {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.action-label {
		font-size: var(--font-size-sm);
		color: var(--color-purple);
		font-weight: 500;
	}

	.race-organizer {
		display: flex;
		align-items: center;
		gap: 0.35rem;
	}

	.organizer-avatar {
		width: 18px;
		height: 18px;
		border-radius: 50%;
	}

	.organizer-link {
		background: none;
		border: none;
		padding: 0;
		color: inherit;
		font: inherit;
		cursor: pointer;
	}

	.organizer-link:hover {
		color: var(--color-purple);
		text-decoration: underline;
	}
</style>
