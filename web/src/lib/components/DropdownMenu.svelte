<script lang="ts">
	interface MenuItem {
		label: string;
		danger?: boolean;
		disabled?: boolean;
		onclick: () => void;
	}

	interface Props {
		items: MenuItem[];
	}

	let { items }: Props = $props();
	let open = $state(false);

	function handleClick(item: MenuItem) {
		if (item.disabled) return;
		open = false;
		item.onclick();
	}

	function handleClickOutside(event: MouseEvent) {
		if (!(event.target as HTMLElement).closest('.dropdown-menu')) {
			open = false;
		}
	}
</script>

<svelte:window onclick={handleClickOutside} />

<div class="dropdown-menu">
	<button class="trigger" onclick={() => (open = !open)} title="More actions">
		<svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
			<circle cx="8" cy="3" r="1.5" />
			<circle cx="8" cy="8" r="1.5" />
			<circle cx="8" cy="13" r="1.5" />
		</svg>
	</button>
	{#if open}
		<div class="menu">
			{#each items as item}
				<button
					class="menu-item"
					class:danger={item.danger}
					disabled={item.disabled}
					onclick={() => handleClick(item)}
				>
					{item.label}
				</button>
			{/each}
		</div>
	{/if}
</div>

<style>
	.dropdown-menu {
		position: relative;
	}

	.trigger {
		background: none;
		border: 1px solid var(--color-border);
		color: var(--color-text-secondary);
		border-radius: var(--radius-sm);
		padding: 0.4rem;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		transition: all var(--transition);
	}

	.trigger:hover {
		border-color: var(--color-text-secondary);
		color: var(--color-text);
	}

	.menu {
		position: absolute;
		right: 0;
		top: calc(100% + 4px);
		background: var(--color-surface-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		min-width: 160px;
		z-index: 50;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
		padding: 0.25rem;
	}

	.menu-item {
		display: block;
		width: 100%;
		padding: 0.5rem 0.75rem;
		background: none;
		border: none;
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		text-align: left;
		cursor: pointer;
		border-radius: var(--radius-sm);
		transition: background var(--transition);
	}

	.menu-item:hover {
		background: rgba(255, 255, 255, 0.05);
	}

	.menu-item.danger {
		color: var(--color-danger);
	}

	.menu-item.danger:hover {
		background: rgba(239, 68, 68, 0.1);
	}

	.menu-item:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
