<script lang="ts">
	import { copyToClipboard } from '$lib/utils/clipboard';

	interface Props {
		raceId: string;
		onClose: () => void;
	}

	let { raceId, onClose }: Props = $props();

	let dagCopied = $state(false);
	let lbCopied = $state(false);
	let lbLines = $state<number | null>(10);
	let dagFollow = $state(false);
	let dagMaxLayers = $state<number>(5);

	let dagUrl = $derived(
		typeof window !== 'undefined'
			? `${window.location.origin}/overlay/race/${raceId}/dag${dagFollow ? `?follow=true${dagMaxLayers !== 5 ? `&maxLayers=${dagMaxLayers}` : ''}` : ''}`
			: ''
	);

	let lbUrl = $derived(
		typeof window !== 'undefined'
			? `${window.location.origin}/overlay/race/${raceId}/leaderboard${lbLines != null ? `?lines=${lbLines}` : ''}`
			: ''
	);

	async function copyUrl(url: string, which: 'dag' | 'lb') {
		const ok = await copyToClipboard(url);
		if (!ok) return;
		if (which === 'dag') {
			dagCopied = true;
			setTimeout(() => (dagCopied = false), 2000);
		} else {
			lbCopied = true;
			setTimeout(() => (lbCopied = false), 2000);
		}
	}
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="modal-backdrop" onclick={onClose} onkeydown={(e) => e.key === 'Escape' && onClose()}>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div class="modal" onclick={(e) => e.stopPropagation()}>
		<div class="modal-header">
			<h2>OBS Overlays</h2>
			<button class="close-btn" onclick={onClose}>&times;</button>
		</div>

		<p class="description">
			Add these as <strong>Browser Sources</strong> in OBS with transparent background.
		</p>

		<div class="overlay-section">
			<h3>DAG</h3>
			<p class="size-hint">Recommended size: 800 &times; 600</p>
			<div class="config-row">
				<label for="dag-follow">
					<input id="dag-follow" type="checkbox" bind:checked={dagFollow} />
					Auto-follow
				</label>
			</div>
			{#if dagFollow}
				<div class="config-row">
					<label for="dag-max-layers">Visible layers</label>
					<input
						id="dag-max-layers"
						type="number"
						min="3"
						max="20"
						bind:value={dagMaxLayers}
						class="config-input"
					/>
				</div>
			{/if}
			<div class="url-row">
				<input type="text" readonly value={dagUrl} class="url-input" />
				<button class="copy-btn" onclick={() => copyUrl(dagUrl, 'dag')}>
					{dagCopied ? 'Copied!' : 'Copy'}
				</button>
			</div>
		</div>

		<div class="overlay-section">
			<h3>Leaderboard</h3>
			<p class="size-hint">Recommended size: 400 &times; 800</p>
			<div class="config-row">
				<label for="lb-lines">Max lines</label>
				<input
					id="lb-lines"
					type="number"
					min="1"
					max="50"
					bind:value={lbLines}
					placeholder="All"
					class="config-input"
				/>
			</div>
			<div class="url-row">
				<input type="text" readonly value={lbUrl} class="url-input" />
				<button class="copy-btn" onclick={() => copyUrl(lbUrl, 'lb')}>
					{lbCopied ? 'Copied!' : 'Copy'}
				</button>
			</div>
		</div>
	</div>
</div>

<style>
	.modal-backdrop {
		position: fixed;
		inset: 0;
		background: rgba(0, 0, 0, 0.6);
		display: flex;
		align-items: center;
		justify-content: center;
		z-index: 1000;
	}

	.modal {
		background: var(--color-surface);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-lg);
		padding: 1.5rem;
		max-width: 500px;
		width: 90%;
	}

	.modal-header {
		display: flex;
		justify-content: space-between;
		align-items: center;
		margin-bottom: 0.75rem;
	}

	.modal-header h2 {
		margin: 0;
		color: var(--color-gold);
		font-size: var(--font-size-lg);
	}

	.close-btn {
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 1.5rem;
		cursor: pointer;
		padding: 0;
		line-height: 1;
	}

	.close-btn:hover {
		color: var(--color-text);
	}

	.description {
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
		margin: 0 0 1rem 0;
	}

	.overlay-section {
		margin-bottom: 1rem;
	}

	.overlay-section:last-child {
		margin-bottom: 0;
	}

	.overlay-section h3 {
		margin: 0 0 0.25rem 0;
		font-size: var(--font-size-base);
		color: var(--color-text);
	}

	.size-hint {
		margin: 0 0 0.5rem 0;
		font-size: var(--font-size-sm);
		color: var(--color-text-disabled);
	}

	.url-row {
		display: flex;
		gap: 0.5rem;
	}

	.url-input {
		flex: 1;
		padding: 0.5rem 0.75rem;
		background: var(--color-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		color: var(--color-text);
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: var(--font-size-sm);
		min-width: 0;
	}

	.copy-btn {
		padding: 0.5rem 1rem;
		background: var(--color-purple);
		color: white;
		border: none;
		border-radius: var(--radius-sm);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		white-space: nowrap;
		transition: background var(--transition);
	}

	.copy-btn:hover {
		background: var(--color-purple-hover, #7c3aed);
	}

	.config-row {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		margin-bottom: 0.5rem;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
	}

	.config-input {
		width: 5rem;
		padding: 0.25rem 0.5rem;
		background: var(--color-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		color: var(--color-text);
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: var(--font-size-sm);
	}

	.config-row label {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		cursor: pointer;
	}
</style>
