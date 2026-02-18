<script lang="ts">
	import type { WsParticipant } from '$lib/websocket';
	import { PLAYER_COLORS } from '$lib/dag/constants';

	interface Props {
		participants: WsParticipant[];
		totalLayers?: number | null;
		mode?: 'running' | 'finished';
		zoneNames?: Map<string, string> | null;
		selectedIds?: Set<string>;
		onToggle?: (id: string, ctrlKey: boolean) => void;
		onClearSelection?: () => void;
	}

	let {
		participants,
		totalLayers = null,
		mode = 'running',
		zoneNames = null,
		selectedIds,
		onToggle,
		onClearSelection
	}: Props = $props();

	let hasSelection = $derived(selectedIds != null && selectedIds.size > 0);

	function zoneName(zone: string | null): string | null {
		if (!zone || !zoneNames) return null;
		const name = zoneNames.get(zone);
		if (!name) return null;
		if (name.length > 20) return name.slice(0, 19) + '\u2026';
		return name;
	}

	function playerColor(participant: WsParticipant): string {
		return PLAYER_COLORS[participant.color_index % PLAYER_COLORS.length];
	}

	function formatIgt(ms: number): string {
		const totalSeconds = Math.floor(ms / 1000);
		const hours = Math.floor(totalSeconds / 3600);
		const minutes = Math.floor((totalSeconds % 3600) / 60);
		const seconds = totalSeconds % 60;
		if (hours > 0) {
			return `${hours}:${minutes.toString().padStart(2, '0')}:${seconds.toString().padStart(2, '0')}`;
		}
		return `${minutes}:${seconds.toString().padStart(2, '0')}`;
	}

	function getStatusClass(status: string): string {
		switch (status) {
			case 'finished':
				return 'finished';
			case 'playing':
				return 'playing';
			case 'ready':
				return 'ready';
			case 'abandoned':
				return 'abandoned';
			default:
				return '';
		}
	}
</script>

<svelte:window
	onkeydown={(e) => {
		if (e.key === 'Escape' && hasSelection && onClearSelection) {
			onClearSelection();
		}
	}}
/>

<div class="leaderboard">
	<div class="leaderboard-header">
		<h2>{mode === 'finished' ? 'Results' : 'Leaderboard'}</h2>
		{#if hasSelection && onClearSelection}
			<button class="show-all-btn" onclick={onClearSelection}>Show all</button>
		{/if}
	</div>

	{#if participants.length === 0}
		<p class="empty">No participants yet</p>
	{:else}
		<ol class="list">
			{#each participants as participant, index (participant.id)}
				{@const color = playerColor(participant)}
				<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
			<li
				class="participant {getStatusClass(participant.status)}"
				class:selected={hasSelection && selectedIds!.has(participant.id)}
				style="border-left: 3px solid {color};"
				onclick={(e) => onToggle?.(participant.id, e.ctrlKey || e.metaKey)}
				role={onToggle ? 'button' : undefined}
				tabindex={onToggle ? 0 : undefined}
			>
						<span class="rank" style="background: {color}; color: #1a1a2e;"
							>{index + 1}</span
						>
					<div class="info">
						{#if participant.status === 'playing'}
							{@const zone = zoneName(participant.current_zone)}
							<div class="name-row">
								<span class="name" style="color: {color};">
									{#if mode === 'running'}
										<span class="conn-dot" class:connected={participant.mod_connected} title={participant.mod_connected ? 'Mod connected' : 'Mod disconnected'}></span>
									{/if}
									{participant.twitch_display_name || participant.twitch_username}
								</span>
								<span class="layer-fraction">{participant.current_layer}{totalLayers ? `/${totalLayers}` : ''}</span>
							</div>
							{#if zone}
								<span class="zone" title={zoneNames?.get(participant.current_zone ?? '') ?? ''}>{zone}</span>
							{/if}
							<span class="stats">
								{formatIgt(participant.igt_ms)}
								{#if participant.death_count > 0}
									<span class="death-count">{participant.death_count}</span>
								{/if}
							</span>
						{:else}
							<span class="name" style="color: {color};">
								{#if mode === 'running' && (participant.status === 'ready' || participant.status === 'registered')}
									<span class="conn-dot" class:connected={participant.mod_connected} title={participant.mod_connected ? 'Mod connected' : 'Mod disconnected'}></span>
								{/if}
								{participant.twitch_display_name || participant.twitch_username}
							</span>
							<span class="stats">
								{#if mode === 'finished' && participant.status === 'finished'}
									<span class="finished-time">{formatIgt(participant.igt_ms)}</span>
									{#if participant.death_count > 0}
										<span class="death-count">{participant.death_count}</span>
									{/if}
								{:else if mode === 'finished' && participant.status === 'abandoned'}
									<span class="dnf"
										>DNF (L{participant.current_layer}{totalLayers ? `/${totalLayers}` : ''})</span
									>
									{#if participant.death_count > 0}
										<span class="death-count">{participant.death_count}</span>
									{/if}
								{:else if participant.status === 'finished'}
									<span class="finished-time">{formatIgt(participant.igt_ms)}</span>
									{#if participant.death_count > 0}
										<span class="death-count">{participant.death_count}</span>
									{/if}
								{:else}
									<span class="status-text">{participant.status}</span>
								{/if}
							</span>
						{/if}
					</div>
					{#if mode === 'running' && participant.status === 'finished'}
						<span class="finish-icon">✓</span>
					{/if}
				</li>
			{/each}
		</ol>
	{/if}
</div>

<style>
	.leaderboard {
		height: 100%;
		display: flex;
		flex-direction: column;
	}

	.leaderboard-header {
		display: flex;
		align-items: baseline;
		justify-content: space-between;
		margin-bottom: 1rem;
	}

	.leaderboard-header h2 {
		color: var(--color-gold);
		margin: 0;
		font-size: var(--font-size-lg);
		font-weight: 600;
	}

	.show-all-btn {
		background: none;
		border: none;
		padding: 0;
		color: var(--color-text-secondary);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		transition: color var(--transition);
	}

	.show-all-btn:hover {
		color: var(--color-text);
	}

	.list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
		overflow-y: auto;
		flex: 1;
	}

	.participant {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem;
		background: var(--color-bg);
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border);
		transition: border-color var(--transition);
		cursor: pointer;
	}

	.participant:hover {
		background: var(--color-surface-elevated);
	}

	.participant.selected {
		background: var(--color-surface-elevated);
	}


	.participant.abandoned {
		opacity: 0.5;
	}

	.rank {
		width: 24px;
		height: 24px;
		background: var(--color-border);
		border-radius: 50%;
		display: flex;
		align-items: center;
		justify-content: center;
		font-size: var(--font-size-sm);
		font-weight: bold;
		flex-shrink: 0;
		color: var(--color-text-secondary);
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

	.stats {
		display: block;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		font-variant-numeric: tabular-nums;
	}

	.finished-time {
		color: var(--color-success);
		font-weight: 500;
		font-variant-numeric: tabular-nums;
	}

	.status-text {
		text-transform: capitalize;
	}

	.finish-icon {
		color: var(--color-success);
		font-size: 1.2rem;
	}

	.death-count {
		color: var(--color-danger, #ef4444);
		font-size: var(--font-size-sm);
	}

	.death-count::before {
		content: '\1F480';
		margin-left: 0.25em;
	}

	.dnf {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.name-row {
		display: flex;
		align-items: baseline;
		gap: 0.5rem;
	}

	.name-row .name {
		flex: 1;
		min-width: 0;
	}

	.layer-fraction {
		font-size: var(--font-size-sm);
		font-weight: 600;
		font-variant-numeric: tabular-nums;
		color: var(--color-text-secondary);
		flex-shrink: 0;
	}

	.zone {
		display: block;
		font-size: var(--font-size-sm);
		color: var(--color-text);
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.conn-dot {
		display: inline-block;
		width: 6px;
		height: 6px;
		border-radius: 50%;
		background: var(--color-text-disabled, #555);
		margin-right: 0.25rem;
		vertical-align: middle;
	}

	.conn-dot.connected {
		background: var(--color-success, #22c55e);
	}

	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
	}
</style>
