<script lang="ts">
	let copied = $state(false);

	async function copyLink() {
		try {
			await navigator.clipboard.writeText(window.location.href);
			copied = true;
			setTimeout(() => (copied = false), 2000);
		} catch {
			// Fallback: select from a temporary input
			const input = document.createElement('input');
			input.value = window.location.href;
			document.body.appendChild(input);
			input.select();
			document.execCommand('copy');
			document.body.removeChild(input);
			copied = true;
			setTimeout(() => (copied = false), 2000);
		}
	}

	async function share() {
		if (navigator.share) {
			try {
				await navigator.share({
					title: document.title,
					url: window.location.href
				});
			} catch {
				// User cancelled or share failed — fall back to copy
				await copyLink();
			}
		} else {
			await copyLink();
		}
	}
</script>

<div class="share-buttons">
	<button class="btn btn-secondary btn-sm" onclick={copyLink}>
		{copied ? 'Copied!' : 'Copy Link'}
	</button>
	{#if typeof navigator !== 'undefined' && 'share' in navigator}
		<button class="btn btn-secondary btn-sm" onclick={share}> Share </button>
	{/if}
</div>

<style>
	.share-buttons {
		display: flex;
		gap: 0.5rem;
	}

	.btn-sm {
		padding: 0.4rem 0.75rem;
		font-size: var(--font-size-sm);
	}
</style>
