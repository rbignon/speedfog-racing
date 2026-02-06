<script lang="ts">
	import type { Caster } from '$lib/api';

	interface Props {
		casters: Caster[];
	}

	let { casters }: Props = $props();
</script>

{#if casters.length > 0}
	<div class="caster-list">
		<h3>Casters</h3>
		<ul>
			{#each casters as caster (caster.id)}
				<li class="caster-item">
					{#if caster.user.twitch_avatar_url}
						<img src={caster.user.twitch_avatar_url} alt="" class="avatar" />
					{:else}
						<div class="avatar-placeholder"></div>
					{/if}
					<span class="name">
						{caster.user.twitch_display_name || caster.user.twitch_username}
					</span>
					<a
						href="https://twitch.tv/{caster.user.twitch_username}"
						target="_blank"
						rel="noopener noreferrer"
						class="twitch-link"
						title="View on Twitch"
					>
						<svg
							width="14"
							height="14"
							viewBox="0 0 24 24"
							fill="none"
							stroke="currentColor"
							stroke-width="2"
							stroke-linecap="round"
							stroke-linejoin="round"
						>
							<path d="M18 13v6a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V8a2 2 0 0 1 2-2h6" />
							<polyline points="15 3 21 3 21 9" />
							<line x1="10" y1="14" x2="21" y2="3" />
						</svg>
					</a>
				</li>
			{/each}
		</ul>
	</div>
{/if}

<style>
	.caster-list {
		margin-top: 1rem;
	}

	h3 {
		color: var(--color-text-secondary);
		margin: 0 0 0.5rem 0;
		font-size: var(--font-size-sm);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	ul {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.caster-item {
		display: flex;
		align-items: center;
		gap: 0.5rem;
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

	.name {
		font-size: var(--font-size-sm);
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.twitch-link {
		color: var(--color-twitch);
		display: flex;
		align-items: center;
		flex-shrink: 0;
	}

	.twitch-link:hover {
		color: var(--color-twitch-hover);
	}
</style>
