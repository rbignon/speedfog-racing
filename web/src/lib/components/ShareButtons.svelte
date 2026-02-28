<script lang="ts">
	import { copyToClipboard } from '$lib/utils/clipboard';

	let copied = $state(false);

	async function copyLink() {
		const ok = await copyToClipboard(window.location.href);
		if (!ok) return;
		copied = true;
		setTimeout(() => (copied = false), 2000);
	}

	async function handleClick() {
		if (typeof navigator !== 'undefined' && 'share' in navigator) {
			try {
				await navigator.share({
					title: document.title,
					url: window.location.href
				});
			} catch {
				await copyLink();
			}
		} else {
			await copyLink();
		}
	}
</script>

<button
	class="share-btn"
	onclick={handleClick}
	title={copied ? 'Copied!' : 'Share'}
	class:copied
>
	{#if copied}
		<svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
			<path
				fill-rule="evenodd"
				d="M16.707 5.293a1 1 0 010 1.414l-8 8a1 1 0 01-1.414 0l-4-4a1 1 0 011.414-1.414L8 12.586l7.293-7.293a1 1 0 011.414 0z"
				clip-rule="evenodd"
			/>
		</svg>
	{:else}
		<svg viewBox="0 0 20 20" fill="currentColor" width="18" height="18">
			<path
				d="M15 8a3 3 0 10-2.977-2.63l-4.94 2.47a3 3 0 100 4.319l4.94 2.47a3 3 0 10.895-1.789l-4.94-2.47a3.027 3.027 0 000-.74l4.94-2.47C13.456 7.68 14.19 8 15 8z"
			/>
		</svg>
	{/if}
</button>

<style>
	.share-btn {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border-radius: var(--radius-sm);
		border: 1px solid var(--color-border);
		background: transparent;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: all var(--transition);
	}

	.share-btn:hover {
		color: var(--color-gold);
		border-color: var(--color-gold);
	}

	.share-btn.copied {
		color: var(--color-success, #22c55e);
		border-color: var(--color-success, #22c55e);
	}
</style>
