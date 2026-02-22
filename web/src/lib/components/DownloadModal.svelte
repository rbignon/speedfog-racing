<script lang="ts">
	interface Props {
		onClose: () => void;
		onDownload: () => void;
		downloading: boolean;
		error: string | null;
	}

	let { onClose, onDownload, downloading, error }: Props = $props();
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
	class="modal-backdrop"
	onclick={onClose}
	onkeydown={(e) => e.key === 'Escape' && onClose()}
>
	<!-- svelte-ignore a11y_no_static_element_interactions -->
	<!-- svelte-ignore a11y_click_events_have_key_events -->
	<div class="modal" onclick={(e) => e.stopPropagation()}>
		<div class="modal-header">
			<h2>Before you race</h2>
			<button class="close-btn" onclick={onClose}>&times;</button>
		</div>

		<div class="section">
			<h3>Rules</h3>
			<ul>
				<li>Glitchless</li>
				<li>Quit-outs are not allowed</li>
				<li>Using LiveSplit is not allowed</li>
				<li>Using other mods is not allowed</li>
				<li>Skips are allowed</li>
			</ul>
		</div>

		<div class="section">
			<h3>Installation</h3>
			<ol>
				<li>Extract the zip anywhere</li>
				<li>Run <code>launch_speedfog.bat</code></li>
			</ol>
		</div>

		<button class="download-btn" onclick={onDownload} disabled={downloading}>
			<svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
				<path
					d="M8 1v9m0 0L5 7m3 3 3-3M3 13h10"
					stroke="currentColor"
					stroke-width="1.5"
					stroke-linecap="round"
					stroke-linejoin="round"
					fill="none"
				/>
			</svg>
			{downloading ? 'Preparing...' : 'Download Race Package'}
		</button>
		{#if error}
			<span class="download-error">{error}</span>
		{/if}
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

	.section {
		margin-bottom: 1rem;
	}

	.section h3 {
		margin: 0 0 0.5rem 0;
		font-size: var(--font-size-base);
		color: var(--color-text);
	}

	.section ul,
	.section ol {
		margin: 0;
		padding-left: 1.25rem;
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
	}

	.section li {
		margin-bottom: 0.25rem;
	}

	.section code {
		background: var(--color-bg);
		padding: 0.1rem 0.4rem;
		border-radius: var(--radius-sm);
		font-family: 'JetBrains Mono', 'Fira Code', monospace;
		font-size: var(--font-size-sm);
	}

	.download-btn {
		width: 100%;
		display: flex;
		align-items: center;
		justify-content: center;
		gap: 0.5rem;
		padding: 0.75rem 1rem;
		background: var(--color-gold);
		color: var(--color-bg);
		border: none;
		border-radius: var(--radius-sm);
		font-family: var(--font-family);
		font-size: var(--font-size-base);
		font-weight: 600;
		cursor: pointer;
		transition: background var(--transition);
	}

	.download-btn:hover:not(:disabled) {
		background: var(--color-gold-hover, #d4a520);
	}

	.download-btn:disabled {
		opacity: 0.6;
		cursor: not-allowed;
	}

	.download-btn svg {
		flex-shrink: 0;
	}

	.download-error {
		display: block;
		text-align: center;
		color: var(--color-danger);
		font-size: var(--font-size-sm);
		margin-top: 0.5rem;
	}
</style>
