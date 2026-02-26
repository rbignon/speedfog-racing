<script lang="ts">
	import { searchUsers, type User } from '$lib/api';
	import { goto } from '$app/navigation';

	let query = $state('');
	let results = $state<User[]>([]);
	let showDropdown = $state(false);
	let loading = $state(false);
	let expanded = $state(false);
	let highlightIndex = $state(-1);

	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	let containerEl: HTMLDivElement | undefined = $state();
	let inputEl: HTMLInputElement | undefined = $state();

	let activeDescendant = $derived(
		highlightIndex >= 0 ? `nav-search-option-${highlightIndex}` : undefined
	);

	function handleInput() {
		highlightIndex = -1;
		if (debounceTimer) clearTimeout(debounceTimer);

		if (query.trim().length < 2) {
			results = [];
			showDropdown = false;
			return;
		}

		debounceTimer = setTimeout(async () => {
			loading = true;
			try {
				results = await searchUsers(query.trim());
				showDropdown = results.length > 0;
			} catch {
				results = [];
				showDropdown = false;
			} finally {
				loading = false;
			}
		}, 300);
	}

	function selectUser(user: User) {
		showDropdown = false;
		query = '';
		results = [];
		highlightIndex = -1;
		collapse();
		goto(`/user/${user.twitch_username}`);
	}

	function handleKeydown(e: KeyboardEvent) {
		if (e.key === 'Escape') {
			e.preventDefault();
			e.stopPropagation();
			if (showDropdown) {
				showDropdown = false;
				highlightIndex = -1;
			} else {
				collapse();
			}
			return;
		}

		if (e.key === 'ArrowDown' && showDropdown) {
			e.preventDefault();
			highlightIndex = Math.min(highlightIndex + 1, results.length - 1);
			return;
		}

		if (e.key === 'ArrowUp' && showDropdown) {
			e.preventDefault();
			highlightIndex = Math.max(highlightIndex - 1, -1);
			return;
		}

		if (e.key === 'Enter' && showDropdown && highlightIndex >= 0 && results[highlightIndex]) {
			e.preventDefault();
			selectUser(results[highlightIndex]);
			return;
		}
	}

	function expand() {
		expanded = true;
		requestAnimationFrame(() => inputEl?.focus());
	}

	function collapse() {
		expanded = false;
		query = '';
		results = [];
		showDropdown = false;
		highlightIndex = -1;
	}

	$effect(() => {
		function handleClickOutside(e: MouseEvent) {
			if (containerEl && !containerEl.contains(e.target as Node)) {
				showDropdown = false;
				highlightIndex = -1;
				if (expanded) collapse();
			}
		}

		document.addEventListener('click', handleClickOutside);
		return () => {
			document.removeEventListener('click', handleClickOutside);
			if (debounceTimer) clearTimeout(debounceTimer);
		};
	});
</script>

{#snippet searchInput()}
	<svg class="search-icon" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
		<path
			fill-rule="evenodd"
			d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z"
			clip-rule="evenodd"
		/>
	</svg>
	<input
		type="text"
		bind:this={inputEl}
		bind:value={query}
		oninput={handleInput}
		onkeydown={handleKeydown}
		placeholder="Search players..."
		role="combobox"
		aria-autocomplete="list"
		aria-expanded={showDropdown}
		aria-controls="nav-search-listbox"
		aria-activedescendant={activeDescendant}
	/>
	{#if loading}
		<span class="search-spinner"></span>
	{/if}
{/snippet}

{#snippet searchDropdown()}
	{#if showDropdown && results.length > 0}
		<ul class="dropdown" role="listbox" id="nav-search-listbox">
			{#each results.slice(0, 6) as user, i (user.id)}
				<li>
					<button
						class="dropdown-item"
						class:highlighted={i === highlightIndex}
						id="nav-search-option-{i}"
						role="option"
						aria-selected={i === highlightIndex}
						onclick={() => selectUser(user)}
					>
						{#if user.twitch_avatar_url}
							<img src={user.twitch_avatar_url} alt="" class="avatar" />
						{:else}
							<div class="avatar-placeholder"></div>
						{/if}
						<span>{user.twitch_display_name || user.twitch_username}</span>
					</button>
				</li>
			{/each}
		</ul>
	{/if}
{/snippet}

<div class="nav-search" bind:this={containerEl}>
	<!-- Desktop: always-visible input -->
	<div class="search-desktop">
		<div class="search-input-wrap">
			{@render searchInput()}
		</div>
		{@render searchDropdown()}
	</div>

	<!-- Mobile: icon button + expandable overlay -->
	<div class="search-mobile">
		{#if !expanded}
			<button class="search-toggle" onclick={expand} aria-label="Search players">
				<svg viewBox="0 0 20 20" fill="currentColor" aria-hidden="true">
					<path
						fill-rule="evenodd"
						d="M8 4a4 4 0 100 8 4 4 0 000-8zM2 8a6 6 0 1110.89 3.476l4.817 4.817a1 1 0 01-1.414 1.414l-4.816-4.816A6 6 0 012 8z"
						clip-rule="evenodd"
					/>
				</svg>
			</button>
		{/if}

		{#if expanded}
			<div class="search-overlay">
				<div class="search-input-wrap">
					{@render searchInput()}
					<button class="search-close" onclick={collapse} aria-label="Close search">
						&times;
					</button>
				</div>
				{@render searchDropdown()}
			</div>
		{/if}
	</div>
</div>

<style>
	.nav-search {
		position: relative;
	}

	/* Desktop: show inline input, hide mobile toggle */
	.search-desktop {
		display: block;
		position: relative;
	}

	.search-mobile {
		display: none;
	}

	@media (max-width: 768px) {
		.search-desktop {
			display: none;
		}

		.search-mobile {
			display: block;
		}
	}

	/* Shared input wrapper */
	.search-input-wrap {
		display: flex;
		align-items: center;
		position: relative;
	}

	.search-input-wrap input {
		width: 180px;
		padding: 0.4rem 0.5rem 0.4rem 1.8rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-bg);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
	}

	.search-input-wrap input::placeholder {
		color: var(--color-text-disabled);
	}

	.search-input-wrap input:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	.search-icon {
		position: absolute;
		left: 0.5rem;
		width: 14px;
		height: 14px;
		color: var(--color-text-secondary);
		pointer-events: none;
	}

	.search-spinner {
		position: absolute;
		right: 0.5rem;
		width: 12px;
		height: 12px;
		border: 2px solid var(--color-border);
		border-top-color: var(--color-purple);
		border-radius: 50%;
		animation: spin 0.6s linear infinite;
	}

	@keyframes spin {
		to {
			transform: rotate(360deg);
		}
	}

	/* Dropdown */
	.dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		z-index: 200;
		list-style: none;
		padding: 0;
		margin: 0.25rem 0 0 0;
		background: var(--color-surface-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		max-height: 240px;
		overflow-y: auto;
		box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
		min-width: 200px;
	}

	.dropdown li + li {
		border-top: 1px solid var(--color-border);
	}

	.dropdown-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		width: 100%;
		padding: 0.5rem 0.75rem;
		background: none;
		border: none;
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
		text-align: left;
	}

	.dropdown-item:hover,
	.dropdown-item.highlighted {
		background: var(--color-surface);
	}

	.avatar {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.avatar-placeholder {
		width: 22px;
		height: 22px;
		border-radius: 50%;
		background: var(--color-border);
		flex-shrink: 0;
	}

	/* Mobile toggle button */
	.search-toggle {
		display: flex;
		align-items: center;
		justify-content: center;
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 1px solid var(--color-border);
		background: none;
		color: var(--color-text-secondary);
		cursor: pointer;
		transition: all var(--transition);
		padding: 0;
	}

	.search-toggle:hover {
		border-color: var(--color-purple);
		color: var(--color-purple);
	}

	.search-toggle svg {
		width: 16px;
		height: 16px;
	}

	/* Mobile overlay */
	.search-overlay {
		position: absolute;
		top: 0;
		right: 0;
		z-index: 150;
		display: flex;
		flex-direction: column;
	}

	.search-overlay .search-input-wrap input {
		width: 200px;
		padding-right: 2rem;
	}

	.search-close {
		position: absolute;
		right: 0.25rem;
		top: 50%;
		transform: translateY(-50%);
		background: none;
		border: none;
		color: var(--color-text-secondary);
		font-size: 1.2rem;
		cursor: pointer;
		padding: 0 0.25rem;
		line-height: 1;
	}

	.search-close:hover {
		color: var(--color-text);
	}
</style>
