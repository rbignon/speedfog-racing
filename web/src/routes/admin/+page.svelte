<script lang="ts">
	import { goto } from '$app/navigation';
	import { auth } from '$lib/stores/auth.svelte';
	import { fetchAdminUsers, updateAdminUserRole, type AdminUser } from '$lib/api';

	let users: AdminUser[] = $state([]);
	let loading = $state(true);
	let error = $state<string | null>(null);
	let authChecked = $state(false);

	$effect(() => {
		if (auth.initialized && !authChecked) {
			authChecked = true;
			if (!auth.isAdmin) {
				goto('/');
				return;
			}
			loadUsers();
		}
	});

	async function loadUsers() {
		try {
			users = await fetchAdminUsers();
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to load users.';
		} finally {
			loading = false;
		}
	}

	async function changeRole(user: AdminUser, newRole: string) {
		try {
			const updated = await updateAdminUserRole(user.id, newRole);
			const idx = users.findIndex((u) => u.id === updated.id);
			if (idx !== -1) {
				users[idx] = updated;
			}
		} catch (e) {
			error = e instanceof Error ? e.message : 'Failed to update role.';
		}
	}

	function formatDate(iso: string | null): string {
		if (!iso) return 'Never';
		const d = new Date(iso);
		return d.toLocaleDateString('en-US', {
			month: 'short',
			day: 'numeric',
			year: 'numeric',
			hour: '2-digit',
			minute: '2-digit',
		});
	}
</script>

<svelte:head>
	<title>Admin - SpeedFog Racing</title>
</svelte:head>

<main>
	<h1>User Management</h1>

	{#if error}
		<div class="error">
			{error}
			<button onclick={() => (error = null)}>&times;</button>
		</div>
	{/if}

	{#if loading}
		<p class="loading">Loading users...</p>
	{:else if users.length === 0}
		<p class="empty">No users found.</p>
	{:else}
		<div class="table-wrapper">
			<table>
				<thead>
					<tr>
						<th>User</th>
						<th>Role</th>
						<th class="num-col">Trainings</th>
						<th class="num-col">Races</th>
						<th>Last Seen</th>
						<th>Joined</th>
					</tr>
				</thead>
				<tbody>
					{#each users as user (user.id)}
						<tr>
							<td class="user-cell">
								{#if user.twitch_avatar_url}
									<img src={user.twitch_avatar_url} alt="" class="avatar" />
								{/if}
								<span class="username">{user.twitch_display_name || user.twitch_username}</span>
							</td>
							<td>
								{#if user.role === 'admin'}
									<span class="role-badge admin">admin</span>
								{:else}
									<select
										value={user.role}
										onchange={(e) => changeRole(user, e.currentTarget.value)}
									>
										<option value="user">user</option>
										<option value="organizer">organizer</option>
									</select>
								{/if}
							</td>
							<td class="num-cell">{user.training_count}</td>
							<td class="num-cell">{user.race_count}</td>
							<td class="date-cell">{formatDate(user.last_seen)}</td>
							<td class="date-cell">{formatDate(user.created_at)}</td>
						</tr>
					{/each}
				</tbody>
			</table>
		</div>
	{/if}
</main>

<style>
	main {
		max-width: 900px;
		margin: 0 auto;
		padding: 2rem;
	}

	h1 {
		color: var(--color-text);
		font-size: var(--font-size-2xl);
		font-weight: 600;
		margin-bottom: 1.5rem;
	}

	.error {
		background: var(--color-danger-dark);
		color: white;
		padding: 0.75rem 1rem;
		border-radius: var(--radius-sm);
		margin-bottom: 1rem;
		display: flex;
		justify-content: space-between;
		align-items: center;
	}

	.error button {
		background: none;
		border: none;
		color: white;
		font-size: 1.25rem;
		cursor: pointer;
	}

	.loading,
	.empty {
		color: var(--color-text-disabled);
		font-style: italic;
	}

	.table-wrapper {
		overflow-x: auto;
	}

	table {
		width: 100%;
		border-collapse: collapse;
	}

	th {
		text-align: left;
		padding: 0.75rem 1rem;
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		text-transform: uppercase;
		letter-spacing: 0.05em;
		border-bottom: 1px solid var(--color-border);
	}

	td {
		padding: 0.75rem 1rem;
		border-bottom: 1px solid var(--color-border);
		vertical-align: middle;
	}

	tr:hover td {
		background: var(--color-surface);
	}

	.user-cell {
		display: flex;
		align-items: center;
		gap: 0.75rem;
	}

	.avatar {
		width: 32px;
		height: 32px;
		border-radius: 50%;
		border: 2px solid var(--color-border);
	}

	.username {
		font-weight: 500;
	}

	.num-col {
		text-align: center;
	}

	.num-cell {
		text-align: center;
		font-variant-numeric: tabular-nums;
	}

	.date-cell {
		font-size: var(--font-size-sm);
		color: var(--color-text-secondary);
		white-space: nowrap;
	}

	.role-badge {
		display: inline-block;
		padding: 0.2rem 0.6rem;
		border-radius: var(--radius-sm);
		font-size: var(--font-size-sm);
		font-weight: 500;
	}

	.role-badge.admin {
		background: var(--color-purple);
		color: white;
	}

	select {
		padding: 0.35rem 0.5rem;
		border: 1px solid var(--color-border);
		border-radius: var(--radius-sm);
		background: var(--color-surface);
		color: var(--color-text);
		font-family: var(--font-family);
		font-size: var(--font-size-sm);
		cursor: pointer;
	}

	select:focus {
		outline: none;
		border-color: var(--color-purple);
	}

	@media (max-width: 640px) {
		main {
			padding: 1rem;
		}

		h1 {
			font-size: var(--font-size-xl);
		}

		th,
		td {
			padding: 0.5rem;
		}
	}
</style>
