<script lang="ts">
	import { onMount } from 'svelte';
	import type { DailyWeekDay, DailyWeekResponse } from '$lib/api';
	import { formatIgt } from '$lib/utils/training';

	interface Props {
		week: DailyWeekResponse;
		userId: string | null;
		variant?: 'home' | 'dashboard';
	}

	let { week, userId, variant = 'home' }: Props = $props();

	let now = $state(Date.now());
	onMount(() => {
		const timer = setInterval(() => (now = Date.now()), 60_000);
		return () => clearInterval(timer);
	});

	const WEEKDAY_LABELS = ['Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat', 'Sun'];

	function countdown(targetIso: string | null): string {
		if (!targetIso) return '';
		const target = new Date(targetIso).getTime();
		const remainingMs = Math.max(0, target - now);
		const days = Math.floor(remainingMs / 86_400_000);
		const hours = Math.floor((remainingMs % 86_400_000) / 3_600_000);
		if (days >= 1) {
			return `${days}d ${hours}h`;
		}
		const minutes = Math.floor((remainingMs % 3_600_000) / 60_000);
		return `${hours}h ${String(minutes).padStart(2, '0')}m`;
	}

	function userResultLabel(day: DailyWeekDay): string | null {
		if (!userId) return null;
		const r = day.my_result;
		if (!r) return null;
		if (r.status === 'finished' && r.placement && r.igt_ms != null) {
			return `${r.placement}/${r.total_finishers} - ${formatIgt(r.igt_ms)}`;
		}
		return null;
	}

	type CellStrip = {
		text: string;
		variant: 'play-now' | 'in-progress' | 'finished' | 'abandoned';
	} | null;

	function cellStrip(day: DailyWeekDay): CellStrip {
		if (day.state === 'today') {
			const r = day.my_result;
			if (!r) return { text: 'Play now', variant: 'play-now' };
			if (r.status === 'finished') return { text: '✓ Done', variant: 'finished' };
			if (r.status === 'abandoned') return { text: 'Abandoned', variant: 'abandoned' };
			// registered, ready, playing
			return { text: 'In progress', variant: 'in-progress' };
		}
		if (day.state === 'past') {
			const r = day.my_result;
			if (!r) return null;
			if (r.status === 'finished') return { text: '✓ Done', variant: 'finished' };
			if (r.status === 'playing') return { text: 'In progress', variant: 'in-progress' };
			// abandoned, registered, ready (signed up but never played)
			return { text: 'Abandoned', variant: 'abandoned' };
		}
		return null;
	}

	function hrefFor(day: DailyWeekDay): string | null {
		if (day.state === 'today') return '/daily';
		if (day.state === 'past') return `/daily/${day.date}`;
		return null;
	}

	let scrollContainer: HTMLDivElement | undefined = $state();
	onMount(() => {
		const el = scrollContainer;
		if (!el) return;
		const todayEl = el.querySelector<HTMLElement>('[data-cell-state="today"]');
		if (!todayEl) return;
		const offset = todayEl.offsetLeft - el.clientWidth / 2 + todayEl.clientWidth / 2;
		el.scrollLeft = Math.max(0, offset);
	});
</script>

<section class="grid-section" class:variant-dashboard={variant === 'dashboard'}>
	<h2>Daily Seed</h2>
	<div class="grid" bind:this={scrollContainer}>
		{#each week.days as day (day.date)}
			{@const href = hrefFor(day)}
			{@const result = userResultLabel(day)}
			<svelte:element
				this={href ? 'a' : 'div'}
				href={href ?? undefined}
				class="cell"
				class:past={day.state === 'past'}
				class:today={day.state === 'today'}
				class:future={day.state === 'future'}
				class:missing-past={day.state === 'missing_past'}
				data-cell-state={day.state}
			>
				<div class="header">
					<span class="weekday">{WEEKDAY_LABELS[day.weekday]}</span>
					{#if day.state === 'today'}
						<span class="badge today">Today</span>
					{:else if day.state === 'past' && day.finishers_count > 0}
						<span class="meta">{day.finishers_count} finishers</span>
					{/if}
				</div>

				{#if day.state === 'missing_past'}
					<span class="muted">No daily</span>
				{:else if day.state === 'future'}
					<span class="pool">{day.pool_display_name ?? 'TBD'}</span>
					<span class="countdown">Opens in {countdown(day.started_at)}</span>
				{:else}
					<span class="pool">{day.pool_display_name ?? 'TBD'}</span>
					{#if day.podium.length > 0}
						<ul class="podium">
							{#each day.podium as entry}
								<li>
									<span class="medal" aria-hidden="true">
										{entry.placement === 1 ? '🥇' : entry.placement === 2 ? '🥈' : '🥉'}
									</span>
									<span class="name">{entry.twitch_display_name ?? entry.twitch_username}</span>
									<span class="igt">{formatIgt(entry.igt_ms)}</span>
								</li>
							{/each}
						</ul>
					{:else if day.state === 'today'}
						{#if day.race_id === null}
							<span class="muted">Daily seed incoming</span>
						{:else if day.participants_count > 0}
							<span class="muted">
								{day.participants_count}
								{day.participants_count === 1 ? 'player' : 'players'}
							</span>
						{/if}
					{:else}
						<span class="muted">No finishers</span>
					{/if}
					{#if result}
						<span class="me">{result}</span>
					{/if}
					{@const strip = cellStrip(day)}
					{#if strip}
						<span class="strip strip-{strip.variant}">{strip.text}</span>
					{/if}
				{/if}
			</svelte:element>
		{/each}
	</div>
</section>

<style>
	.grid-section {
		margin-bottom: 1.5rem;
	}

	h2 {
		margin: 0 0 0.75rem;
		color: var(--color-gold);
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	.grid {
		display: grid;
		grid-template-columns: repeat(7, 1fr);
		gap: 0.5rem;
	}

	.cell {
		display: flex;
		flex-direction: column;
		gap: 0.25rem;
		padding: 0.75rem 0.875rem;
		min-height: 150px;
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		text-decoration: none;
		color: inherit;
		transition: border-color var(--transition);
	}
	a.cell:hover {
		border-color: var(--color-purple);
		box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
	}

	.cell.today {
		box-shadow: 0 0 20px rgba(200, 164, 78, 0.18);
	}
	a.cell.today:hover {
		box-shadow:
			0 0 20px rgba(200, 164, 78, 0.18),
			0 2px 8px rgba(0, 0, 0, 0.2);
	}

	.cell.future,
	.cell.missing-past {
		border-style: dashed;
		opacity: 0.55;
		cursor: not-allowed;
	}

	.header {
		display: flex;
		justify-content: space-between;
		align-items: baseline;
	}
	.weekday {
		font-size: var(--font-size-xs);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		font-weight: 600;
		color: var(--color-text-secondary);
	}
	.meta {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
	}
	.badge.today {
		padding: 0;
		font-size: var(--font-size-xs);
		color: var(--color-gold);
		font-weight: 600;
	}

	.pool {
		font-weight: 600;
		color: var(--color-text);
		font-size: var(--font-size-sm);
	}

	.podium {
		list-style: none;
		margin: 0;
		padding: 0;
		display: flex;
		flex-direction: column;
		gap: 2px;
		font-size: var(--font-size-xs);
	}
	.podium li {
		display: flex;
		gap: 0.35rem;
		align-items: baseline;
	}
	.podium .name {
		color: var(--color-text);
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}
	.podium .igt {
		margin-left: auto;
		color: var(--color-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	.me {
		padding-top: 0.4rem;
		border-top: 1px dashed var(--color-border);
		color: var(--color-text-secondary);
		font-size: var(--font-size-xs);
		font-variant-numeric: tabular-nums;
	}
	.strip {
		margin-top: auto;
		padding: 0.4rem 0;
		text-align: center;
		font-weight: 700;
		font-size: var(--font-size-sm);
		text-transform: uppercase;
		letter-spacing: 0.1em;
		border-radius: 0 0 calc(var(--radius-md) - 1px) calc(var(--radius-md) - 1px);
		margin-left: -0.875rem;
		margin-right: -0.875rem;
		margin-bottom: -0.75rem;
	}
	.strip-play-now {
		background: rgba(16, 185, 129, 0.12);
		color: var(--color-success);
	}
	.strip-finished {
		background: rgba(107, 114, 128, 0.18);
		color: var(--color-success);
	}
	.strip-in-progress {
		background: rgba(245, 158, 11, 0.14);
		color: #f59e0b;
	}
	.strip-abandoned {
		background: rgba(107, 114, 128, 0.18);
		color: var(--color-text-disabled);
	}
	.countdown {
		margin-top: auto;
		color: var(--color-text);
		font-variant-numeric: tabular-nums;
		font-size: var(--font-size-sm);
	}
	.muted {
		color: var(--color-text-disabled);
		font-style: italic;
		font-size: var(--font-size-xs);
	}

	@media (max-width: 640px) {
		.grid {
			display: flex;
			grid-template-columns: none;
			overflow-x: auto;
			scroll-snap-type: x mandatory;
		}
		.cell {
			flex: 0 0 auto;
			min-width: 150px;
			scroll-snap-align: center;
		}
	}
</style>
