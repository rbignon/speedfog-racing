<script lang="ts">
	import type { Race, RaceStatus } from '$lib/api';
	import { goto } from '$app/navigation';
	import { timeAgo, formatScheduledTime } from '$lib/utils/time';
	import { formatPoolName } from '$lib/utils/format';
	import { statusLabel } from '$lib/format';
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
	let winner = $derived(
		race.status === 'finished' && race.participant_previews[0]?.placement === 1
			? race.participant_previews[0]
			: null
	);

	function statusBorderClass(status: RaceStatus): string {
		switch (status) {
			case 'setup':
				return 'border-setup';
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
		if (userRole === 'Organizing' && status === 'setup') return 'Set up →';
		return null;
	}

	let action = $derived(actionLabel(race.status, role));
	let showScheduled = $derived(race.scheduled_at && race.status === 'setup');
	let relativeTime = $derived(
		showScheduled ? formatScheduledTime(race.scheduled_at!) : timeAgo(race.created_at)
	);
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
			<span class="badge badge-{race.status}">{statusLabel(race.status)}</span>
		</div>
	</div>

	{#if race.participant_previews.length > 0}
		<div class="avatar-row" class:has-winner={winner}>
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
			{#if winner}
				<div class="winner-info">
					<svg class="trophy-icon" viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
						<path d="M12 2C9.24 2 7 4.24 7 7h-3c-1.1 0-2 .9-2 2v2c0 2.21 1.79 4 4 4h.68A7.01 7.01 0 0012 19.87V22H8v2h8v-2h-4v-2.13A7.01 7.01 0 0017.32 15H18c2.21 0 4-1.79 4-4V9c0-1.1-.9-2-2-2h-3c0-2.76-2.24-5-5-5zM4 11V9h3v4.83C5.17 13.1 4 11.65 4 11zm16 0c0 1.65-1.17 3.1-3 3.83V9h3v2z"/>
					</svg>
					{#if winner.twitch_avatar_url}
						<img src={winner.twitch_avatar_url} alt="" class="winner-avatar" />
					{/if}
					<span class="winner-name">{winner.twitch_display_name || winner.twitch_username}</span>
				</div>
			{/if}
			<span class="relative-time">{relativeTime}</span>
		</div>
	{:else}
		<div class="avatar-row">
			<span class="no-participants">No players yet</span>
			<span class="relative-time">{relativeTime}</span>
		</div>
	{/if}

	{#if isRunning && race.casters.length > 0}
		<div class="caster-row">
			<svg class="twitch-icon" viewBox="0 0 24 24" fill="currentColor" width="14" height="14">
				<path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/>
			</svg>
			{#each race.casters as caster, i}
				{#if i > 0}<span class="caster-sep">&middot;</span>{/if}
				<button
					class="caster-name"
					onclick={(e: MouseEvent) => {
						e.preventDefault();
						e.stopPropagation();
						window.open(`https://twitch.tv/${caster.user.twitch_username}`, '_blank', 'noopener,noreferrer');
					}}
				>{caster.user.twitch_display_name || caster.user.twitch_username}</button>
			{/each}
		</div>
	{/if}

	<div class="race-meta">
		<span>
			{race.participant_count} player{race.participant_count !== 1 ? 's' : ''}
			{#if race.pool_name}
				&middot; {formatPoolName(race.pool_name)}
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
	.border-setup {
		border-left: 3px solid var(--color-info);
	}

	.border-running {
		border-left: 3px solid var(--color-danger);
	}

	.border-finished {
		border-left: 3px solid var(--color-success);
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
		min-width: 126px;
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

	/* Caster row */
	.caster-row {
		display: flex;
		align-items: center;
		gap: 0.35rem;
		font-size: var(--font-size-xs);
		color: var(--color-twitch, #9146ff);
		margin-bottom: 0.5rem;
		overflow: hidden;
		white-space: nowrap;
		text-overflow: ellipsis;
	}

	.twitch-icon {
		flex-shrink: 0;
		width: 12px;
		height: 12px;
	}

	.caster-sep {
		color: var(--color-text-disabled);
	}

	.caster-name {
		background: none;
		border: none;
		padding: 0;
		font: inherit;
		color: var(--color-twitch, #9146ff);
		cursor: pointer;
	}

	.caster-name:hover {
		text-decoration: underline;
	}

	/* Winner info (inline in avatar row) */
	.winner-info {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		color: var(--color-gold);
		min-width: 0;
		overflow: hidden;
	}

	.trophy-icon {
		flex-shrink: 0;
		width: 16px;
		height: 16px;
	}

	.winner-avatar {
		width: 20px;
		height: 20px;
		border-radius: 50%;
		object-fit: cover;
	}

	.winner-name {
		font-weight: 600;
		font-size: var(--font-size-sm);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
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

	@media (max-width: 640px) {
		.avatar-row.has-winner {
			flex-wrap: wrap;
		}

		.avatar-row.has-winner .winner-info {
			order: -1;
			width: 100%;
			margin-bottom: 0.35rem;
		}
	}
</style>
