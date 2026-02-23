<script lang="ts">
	import type { ReplayState } from './types';

	interface Props {
		replayState: ReplayState;
		/** Current position in replay, 0–1 */
		progress: number;
		/** Current playback speed multiplier */
		speed: number;
		onplay: () => void;
		onpause: () => void;
		onseek: (progress: number) => void;
		onspeed: (speed: number) => void;
	}

	let { replayState, progress, speed, onplay, onpause, onseek, onspeed }: Props = $props();

	let progressBar: HTMLDivElement | undefined = $state();
	let isDragging = $state(false);

	function handleProgressClick(e: MouseEvent) {
		if (!progressBar) return;
		const rect = progressBar.getBoundingClientRect();
		const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
		onseek(ratio);
	}

	function handlePointerDown(e: PointerEvent) {
		isDragging = true;
		(e.target as HTMLElement).setPointerCapture(e.pointerId);
		handleProgressClick(e);
	}

	function handlePointerMove(e: PointerEvent) {
		if (!isDragging) return;
		handleProgressClick(e);
	}

	function handlePointerUp() {
		isDragging = false;
	}

	const speeds = [0.5, 1, 2];

	function formatTime(progressVal: number, durationSec: number): string {
		const sec = Math.floor(progressVal * durationSec);
		const m = Math.floor(sec / 60);
		const s = sec % 60;
		return `${m}:${String(s).padStart(2, '0')}`;
	}
</script>

<div class="replay-controls">
	<button
		class="play-btn"
		onclick={() => (replayState === 'playing' ? onpause() : onplay())}
		aria-label={replayState === 'playing' ? 'Pause' : 'Play'}
	>
		{#if replayState === 'playing'}
			<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
				<rect x="6" y="5" width="4" height="14" rx="1" />
				<rect x="14" y="5" width="4" height="14" rx="1" />
			</svg>
		{:else}
			<svg viewBox="0 0 24 24" width="20" height="20" fill="currentColor">
				<polygon points="6,4 20,12 6,20" />
			</svg>
		{/if}
	</button>

	<span class="time-display">{formatTime(progress, 60)}</span>

	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<div
		class="progress-bar"
		bind:this={progressBar}
		onpointerdown={handlePointerDown}
		onpointermove={handlePointerMove}
		onpointerup={handlePointerUp}
	>
		<div class="progress-fill" style="width: {progress * 100}%"></div>
		<div class="progress-thumb" style="left: {progress * 100}%"></div>
	</div>

	<span class="time-display">1:00</span>

	<div class="speed-selector">
		{#each speeds as s}
			<button class="speed-btn" class:active={speed === s} onclick={() => onspeed(s)}>
				{s}x
			</button>
		{/each}
	</div>
</div>

<style>
	.replay-controls {
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.75rem 1rem;
		background: var(--color-surface);
		border-radius: var(--radius-lg);
		border: 1px solid var(--color-border);
	}

	.play-btn {
		all: unset;
		display: flex;
		align-items: center;
		justify-content: center;
		width: 36px;
		height: 36px;
		border-radius: 50%;
		background: var(--color-gold);
		color: var(--color-bg);
		cursor: pointer;
		flex-shrink: 0;
		transition: background var(--transition);
	}

	.play-btn:hover {
		background: var(--color-gold-hover);
	}

	.time-display {
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		font-variant-numeric: tabular-nums;
		min-width: 3rem;
		text-align: center;
		flex-shrink: 0;
	}

	.progress-bar {
		flex: 1;
		height: 6px;
		background: var(--color-border);
		border-radius: 3px;
		position: relative;
		cursor: pointer;
		touch-action: none;
	}

	.progress-fill {
		height: 100%;
		background: var(--color-gold);
		border-radius: 3px;
		pointer-events: none;
	}

	.progress-thumb {
		position: absolute;
		top: 50%;
		width: 14px;
		height: 14px;
		background: var(--color-gold);
		border: 2px solid var(--color-bg);
		border-radius: 50%;
		transform: translate(-50%, -50%);
		pointer-events: none;
		transition: transform 0.1s ease;
	}

	.progress-bar:hover .progress-thumb {
		transform: translate(-50%, -50%) scale(1.2);
	}

	.speed-selector {
		display: flex;
		gap: 0.25rem;
		flex-shrink: 0;
	}

	.speed-btn {
		all: unset;
		font-family: var(--font-family);
		font-size: var(--font-size-xs);
		color: var(--color-text-disabled);
		padding: 0.2rem 0.4rem;
		border-radius: var(--radius-sm);
		cursor: pointer;
		transition: all var(--transition);
	}

	.speed-btn:hover {
		color: var(--color-text-secondary);
	}

	.speed-btn.active {
		background: var(--color-border);
		color: var(--color-text);
		font-weight: 600;
	}
</style>
