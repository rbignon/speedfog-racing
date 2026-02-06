<script lang="ts">
	import { searchUsers, addParticipant, addCaster, type User } from '$lib/api';

	interface Props {
		mode: 'participant' | 'caster';
		raceId: string;
		onAdded: () => void;
	}

	let { mode, raceId, onAdded }: Props = $props();

	let query = $state('');
	let results = $state<User[]>([]);
	let showDropdown = $state(false);
	let loading = $state(false);
	let adding = $state(false);
	let error = $state<string | null>(null);

	let debounceTimer: ReturnType<typeof setTimeout> | undefined;
	let containerEl: HTMLDivElement | undefined;

	function handleInput() {
		error = null;
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

	async function selectUser(user: User) {
		showDropdown = false;
		adding = true;
		error = null;
		try {
			if (mode === 'caster') {
				await addCaster(raceId, user.twitch_username);
			} else {
				await addParticipant(raceId, user.twitch_username);
			}
			query = '';
			results = [];
			onAdded();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to add';
		} finally {
			adding = false;
		}
	}

	async function handleKeydown(e: KeyboardEvent) {
		if (e.key !== 'Enter') return;
		if (mode === 'caster') return; // casters must select from dropdown
		if (!query.trim()) return;

		e.preventDefault();
		showDropdown = false;
		adding = true;
		error = null;
		try {
			await addParticipant(raceId, query.trim());
			query = '';
			results = [];
			onAdded();
		} catch (err) {
			error = err instanceof Error ? err.message : 'Failed to add';
		} finally {
			adding = false;
		}
	}

	$effect(() => {
		function handleClickOutside(e: MouseEvent) {
			if (containerEl && !containerEl.contains(e.target as Node)) {
				showDropdown = false;
			}
		}

		document.addEventListener('click', handleClickOutside);
		return () => {
			document.removeEventListener('click', handleClickOutside);
			if (debounceTimer) clearTimeout(debounceTimer);
		};
	});
</script>

<div class="search-container" bind:this={containerEl}>
	<div class="search-input-row">
		<input
			type="text"
			bind:value={query}
			oninput={handleInput}
			onkeydown={handleKeydown}
			placeholder={mode === 'caster' ? 'Search Twitch username...' : 'Twitch username...'}
			disabled={adding}
		/>
		{#if loading}
			<span class="search-spinner"></span>
		{/if}
	</div>

	{#if showDropdown && results.length > 0}
		<ul class="dropdown">
			{#each results as user (user.id)}
				<li>
					<button class="dropdown-item" onclick={() => selectUser(user)} disabled={adding}>
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

	{#if error}
		<span class="error">{error}</span>
	{/if}
	{#if adding}
		<span class="adding">Adding...</span>
	{/if}
</div>

<style>
	.search-container {
		position: relative;
	}

	.search-input-row {
		display: flex;
		align-items: center;
		position: relative;
	}

	.search-input-row input {
		width: 100%;
		padding: 0.75rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-bg);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: 1rem;
	}

	.search-input-row input:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	.search-spinner {
		position: absolute;
		right: 0.75rem;
		width: 14px;
		height: 14px;
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

	.dropdown {
		position: absolute;
		top: 100%;
		left: 0;
		right: 0;
		z-index: 10;
		list-style: none;
		padding: 0;
		margin: 0.25rem 0 0 0;
		background: var(--color-surface-elevated);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		max-height: 200px;
		overflow-y: auto;
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
		font-size: var(--font-size-base);
		cursor: pointer;
		text-align: left;
	}

	.dropdown-item:hover {
		background: var(--color-surface);
	}

	.avatar {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		flex-shrink: 0;
	}

	.avatar-placeholder {
		width: 24px;
		height: 24px;
		border-radius: 50%;
		background: var(--color-border);
		flex-shrink: 0;
	}

	.error {
		display: block;
		margin-top: 0.4rem;
		color: var(--color-danger);
		font-size: var(--font-size-sm);
	}

	.adding {
		display: block;
		margin-top: 0.4rem;
		color: var(--color-text-secondary);
		font-size: var(--font-size-sm);
	}
</style>
