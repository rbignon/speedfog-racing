<script lang="ts">
	import type { Caster } from '$lib/api';

	let { casters }: { casters: Caster[] } = $props();
</script>

{#if casters.length > 0}
	<div class="watch-live">
		<h3 class="watch-live-header">
			<svg viewBox="0 0 24 24" fill="currentColor" width="16" height="16">
				<path d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"/>
			</svg>
			Watch Live
		</h3>
		<div class="caster-list">
			{#each casters as caster (caster.id)}
				<a
					href="https://twitch.tv/{caster.user.twitch_username}"
					target="_blank"
					rel="noopener noreferrer"
					class="caster-card"
				>
					{#if caster.user.twitch_avatar_url}
						<img
							src={caster.user.twitch_avatar_url}
							alt={caster.user.twitch_display_name || caster.user.twitch_username}
							class="caster-avatar"
						/>
					{:else}
						<div class="caster-avatar caster-avatar-placeholder">
							{(caster.user.twitch_display_name || caster.user.twitch_username).charAt(0).toUpperCase()}
						</div>
					{/if}
					<div class="caster-info">
						<span class="caster-name">
							{caster.user.twitch_display_name || caster.user.twitch_username}
						</span>
						<span class="caster-sub">Watch on Twitch</span>
					</div>
				</a>
			{/each}
		</div>
	</div>
{/if}

<style>
	.watch-live {
		background: rgba(233, 25, 22, 0.1);
		border: 1px solid rgba(233, 25, 22, 0.25);
		border-radius: var(--radius-sm);
		padding: 0.75rem;
		margin-bottom: 0.75rem;
	}

	.watch-live-header {
		display: flex;
		align-items: center;
		gap: 0.4rem;
		margin: 0 0 0.5rem 0;
		font-size: var(--font-size-sm);
		font-weight: 600;
		color: #f87171;
		text-transform: uppercase;
		letter-spacing: 0.05em;
	}

	.watch-live-header svg {
		width: 14px;
		height: 14px;
		flex-shrink: 0;
	}

	.caster-list {
		display: flex;
		flex-direction: column;
		gap: 0.4rem;
	}

	.caster-card {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.4rem 0.5rem;
		border-radius: var(--radius-sm);
		text-decoration: none;
		color: inherit;
		transition: background var(--transition);
	}

	.caster-card:hover {
		background: rgba(233, 25, 22, 0.15);
	}

	.caster-avatar {
		width: 36px;
		height: 36px;
		border-radius: 50%;
		flex-shrink: 0;
		object-fit: cover;
	}

	.caster-avatar-placeholder {
		display: flex;
		align-items: center;
		justify-content: center;
		background: rgba(233, 25, 22, 0.12);
		color: #f87171;
		font-size: var(--font-size-sm);
		font-weight: 600;
	}

	.caster-info {
		display: flex;
		flex-direction: column;
		min-width: 0;
	}

	.caster-name {
		font-size: var(--font-size-sm);
		font-weight: 500;
		white-space: nowrap;
		overflow: hidden;
		text-overflow: ellipsis;
	}

	.caster-sub {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
	}
</style>
