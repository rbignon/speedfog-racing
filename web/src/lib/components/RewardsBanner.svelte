<script lang="ts">
	import { onMount } from 'svelte';
	import { goto } from '$app/navigation';
	import {
		fetchRewardNotifications,
		dismissRewardNotifications,
		type RewardNotificationDto
	} from '$lib/api';

	let notifs = $state<RewardNotificationDto[]>([]);

	onMount(async () => {
		notifs = await fetchRewardNotifications();
	});

	let summary = $derived.by(() => {
		const granted = notifs.filter(
			(n) =>
				n.kind === 'badge_granted' ||
				n.kind === 'name_template_unlocked' ||
				n.kind === 'phantom_skin_unlocked'
		).length;
		const revoked = notifs.filter((n) => n.kind === 'badge_revoked').length;
		const parts: string[] = [];
		if (granted) parts.push(`${granted} reward${granted > 1 ? 's' : ''} unlocked`);
		if (revoked) parts.push(`${revoked} reward${revoked > 1 ? 's' : ''} lost`);
		return parts.join(', ');
	});

	async function dismiss() {
		await dismissRewardNotifications();
		notifs = [];
	}

	async function view() {
		await dismiss();
		await goto('/settings#rewards');
	}
</script>

{#if notifs.length > 0}
	<div class="rewards-banner" data-testid="rewards-banner">
		<span class="rewards-banner-icon">&#127942;</span>
		<p class="rewards-banner-text">{summary}</p>
		<button class="btn btn-primary" onclick={view}>View</button>
		<button class="rewards-banner-close" onclick={dismiss} aria-label="Dismiss">&times;</button>
	</div>
{/if}

<style>
	.rewards-banner {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		background: var(--color-surface-elevated);
		border: 1px solid var(--color-border);
		border-left: 3px solid var(--color-gold, #ffd700);
		border-radius: var(--radius-sm);
		margin-bottom: 1rem;
	}

	.rewards-banner-icon {
		font-size: 1.25rem;
	}

	.rewards-banner-text {
		flex: 1;
		margin: 0;
		color: var(--color-text);
	}

	.rewards-banner-close {
		background: none;
		border: none;
		font-size: 1.5rem;
		line-height: 1;
		color: var(--color-text-secondary);
		cursor: pointer;
		padding: 0 0.25rem;
	}

	.rewards-banner-close:hover {
		color: var(--color-text);
	}
</style>
