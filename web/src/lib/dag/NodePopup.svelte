<script lang="ts">
	import type { NodePopupData } from './popupData';
	import { formatIgt } from './popupData';
	import { NODE_COLORS } from './constants';

	interface Props {
		data: NodePopupData;
		x: number;
		y: number;
		onclose: () => void;
	}

	let { data, x, y, onclose }: Props = $props();

	// Type label mapping
	const TYPE_LABELS: Record<string, string> = {
		start: 'Starting Area',
		final_boss: 'Final Boss',
		legacy_dungeon: 'Legacy Dungeon',
		major_boss: 'Major Boss',
		boss_arena: 'Boss Arena',
		mini_dungeon: 'Mini Dungeon'
	};

	let popupEl: HTMLDivElement | undefined = $state();

	// Clamp position to viewport after mount (initialized by $effect below)
	let adjustedX = $state(0);
	let adjustedY = $state(0);

	$effect(() => {
		if (!popupEl) return;
		const rect = popupEl.getBoundingClientRect();
		const pad = 12;
		let nx = x + 16; // offset right of click
		let ny = y - 8; // slightly above click

		// Clamp right edge
		if (nx + rect.width > window.innerWidth - pad) {
			nx = x - rect.width - 16; // flip to left
		}
		// Clamp bottom edge
		if (ny + rect.height > window.innerHeight - pad) {
			ny = window.innerHeight - rect.height - pad;
		}
		// Clamp top edge
		if (ny < pad) {
			ny = pad;
		}
		// Clamp left edge
		if (nx < pad) {
			nx = pad;
		}

		adjustedX = nx;
		adjustedY = ny;
	});

	// Close on pointerdown outside (not click — avoids race with onnodeclick which fires on pointerup)
	function onWindowPointerDown(e: PointerEvent) {
		if (popupEl && !popupEl.contains(e.target as Node)) {
			onclose();
		}
	}

	let typeColor = $derived(NODE_COLORS[data.type] ?? '#999');
</script>

<svelte:window onpointerdown={onWindowPointerDown} />

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	bind:this={popupEl}
	class="node-popup"
	style="left: {adjustedX}px; top: {adjustedY}px;"
	onpointerdown={(e) => e.stopPropagation()}
>
	<!-- Header -->
	<div class="popup-header">
		<div class="popup-title">
			<span class="popup-name">{data.displayName}</span>
			<button class="popup-close" onclick={onclose}>&times;</button>
		</div>
		<div class="popup-meta">
			<span class="type-badge" style="color: {typeColor};"
				>{data.displayType ?? TYPE_LABELS[data.type] ?? data.type}</span
			>
			{#if data.tier > 0}
				<span class="tier-badge">Tier {data.tier}</span>
			{/if}
		</div>
	</div>

	<!-- Connections -->
	{#if data.entrances.length > 0}
		<div class="popup-section">
			<div class="section-title">Entrances</div>
			{#each data.entrances as conn}
				<div class="conn-item">
					<span class="conn-arrow entrance">&larr;</span>
					<div class="conn-details">
						<span class="conn-name" class:undiscovered={!conn.displayName}>
							{conn.displayName ?? '???'}
						</span>
						{#if conn.text}
							<span class="conn-text">{conn.text}</span>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}

	{#if data.exits.length > 0}
		<div class="popup-section">
			<div class="section-title">Exits</div>
			{#each data.exits as conn}
				<div class="conn-item">
					<span class="conn-arrow exit">&rarr;</span>
					<div class="conn-details">
						<span class="conn-name" class:undiscovered={!conn.displayName}>
							{conn.displayName ?? '???'}
						</span>
						{#if conn.text}
							<span class="conn-text">{conn.text}</span>
						{/if}
					</div>
				</div>
			{/each}
		</div>
	{/if}

	<!-- Players at this node (live/results) -->
	{#if data.playersHere && data.playersHere.length > 0}
		<div class="popup-section">
			<div class="section-title">Players here</div>
			<div class="player-list">
				{#each data.playersHere as player}
					<span class="player-chip">
						<span class="player-dot" style="background: {player.color};"></span>
						{player.displayName}
					</span>
				{/each}
			</div>
		</div>
	{/if}

	<!-- Visitors (results only) -->
	{#if data.visitors && data.visitors.length > 0}
		<div class="popup-section">
			<div class="section-title">Visited by</div>
			{#each data.visitors as visitor}
				<div class="visitor-item">
					<span class="player-dot" style="background: {visitor.color};"></span>
					<span class="visitor-name">{visitor.displayName}</span>
					<span class="visitor-times">
						<span class="visitor-time">{formatIgt(visitor.arrivedAtMs)}</span>
						{#if visitor.timeSpentMs}
							<span class="visitor-duration">({formatIgt(visitor.timeSpentMs)})</span>
						{/if}
					</span>
				</div>
			{/each}
		</div>
	{/if}
</div>

<style>
	.node-popup {
		position: fixed;
		z-index: 100;
		background: linear-gradient(135deg, #162032 0%, #0f1923 100%);
		border: 1px solid var(--color-border, #253550);
		border-radius: 8px;
		padding: 12px 16px;
		min-width: 200px;
		max-width: 320px;
		max-height: 70vh;
		overflow-y: auto;
		box-shadow: 0 4px 20px rgba(0, 0, 0, 0.5);
		font-size: 0.85rem;
		color: var(--color-text, #e8e6e1);
		pointer-events: auto;
	}

	.popup-header {
		margin-bottom: 8px;
	}

	.popup-title {
		display: flex;
		justify-content: space-between;
		align-items: flex-start;
		gap: 8px;
	}

	.popup-name {
		font-size: 1rem;
		font-weight: 600;
		line-height: 1.3;
	}

	.popup-close {
		background: none;
		border: none;
		color: var(--color-text-secondary, #9ca3af);
		font-size: 1.2rem;
		cursor: pointer;
		padding: 0;
		line-height: 1;
		flex-shrink: 0;
	}

	.popup-close:hover {
		color: var(--color-text, #e8e6e1);
	}

	.popup-meta {
		display: flex;
		gap: 8px;
		align-items: center;
		margin-top: 2px;
	}

	.type-badge {
		font-size: 0.75rem;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.tier-badge {
		font-size: 0.75rem;
		color: var(--color-gold, #c8a44e);
	}

	.popup-section {
		margin-top: 10px;
		padding-top: 8px;
		border-top: 1px solid rgba(255, 255, 255, 0.06);
	}

	.section-title {
		font-size: 0.7rem;
		text-transform: uppercase;
		letter-spacing: 0.1em;
		color: var(--color-text-disabled, #6b7280);
		margin-bottom: 4px;
	}

	.conn-item {
		display: flex;
		align-items: flex-start;
		gap: 6px;
		padding: 2px 0;
	}

	.conn-arrow {
		font-size: 0.8rem;
		flex-shrink: 0;
	}

	.conn-arrow.entrance {
		color: var(--color-text-secondary, #9ca3af);
	}

	.conn-arrow.exit {
		color: var(--color-gold, #c8a44e);
	}

	.conn-details {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.conn-name {
		color: var(--color-text, #e8e6e1);
	}

	.conn-name.undiscovered {
		color: var(--color-text-disabled, #6b7280);
		font-style: italic;
	}

	.conn-text {
		font-size: 0.7rem;
		color: var(--color-text-disabled, #6b7280);
		font-style: italic;
		line-height: 1.3;
	}

	.player-list {
		display: flex;
		flex-wrap: wrap;
		gap: 6px;
	}

	.player-chip {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		font-size: 0.8rem;
	}

	.player-dot {
		display: inline-block;
		width: 8px;
		height: 8px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.visitor-item {
		display: flex;
		align-items: center;
		gap: 6px;
		padding: 2px 0;
		font-size: 0.8rem;
	}

	.visitor-name {
		flex: 1;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.visitor-times {
		display: flex;
		gap: 4px;
		flex-shrink: 0;
		font-variant-numeric: tabular-nums;
	}

	.visitor-time {
		color: var(--color-text-secondary, #9ca3af);
	}

	.visitor-duration {
		color: var(--color-text-disabled, #6b7280);
	}
</style>
