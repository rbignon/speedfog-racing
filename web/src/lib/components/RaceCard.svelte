<script lang="ts">
	import type { Race } from '$lib/api';
	import LiveIndicator from './LiveIndicator.svelte';

	let {
		race,
		role,
		variant = 'default',
	}: {
		race: Race;
		role?: string;
		variant?: 'default' | 'compact';
	} = $props();

	let isRunning = $derived(race.status === 'running');
	let displayName = $derived(
		race.organizer.twitch_display_name || race.organizer.twitch_username,
	);
</script>

<a
	href="/race/{race.id}"
	class="race-card"
	class:running={isRunning}
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
	<div class="race-meta">
		<span>
			{race.participant_count} player{race.participant_count !== 1 ? 's' : ''}
			{#if race.pool_name}
				&middot; {race.pool_name}
			{/if}
		</span>
		<span class="race-organizer">
			by
			{#if race.organizer.twitch_avatar_url}
				<img src={race.organizer.twitch_avatar_url} alt="" class="organizer-avatar" />
			{/if}
			{displayName}
		</span>
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

	.race-card.running {
		border-left: 3px solid var(--color-gold);
	}

	.race-card.compact {
		padding: 0.75rem 1rem;
	}

	.race-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.4rem;
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

	.compact .race-name {
		font-size: 0.95rem;
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

	.race-meta {
		display: flex;
		justify-content: space-between;
		align-items: center;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
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
</style>
