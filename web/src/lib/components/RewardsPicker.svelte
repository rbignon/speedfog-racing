<script lang="ts">
	import type { AuthUser, MyInventoryDto, NameTemplateDef } from '$lib/api';
	import { rewards } from '$lib/stores/rewards.svelte';

	interface Props {
		inventory: MyInventoryDto;
		user: AuthUser;
		selectedTemplateId: string;
		selectedBadgeId: string | null;
	}

	let {
		inventory,
		user,
		selectedTemplateId = $bindable(),
		selectedBadgeId = $bindable()
	}: Props = $props();

	let displayName = $derived(user.twitch_display_name || user.twitch_username);

	let selectedTemplate = $derived(
		inventory.unlocked_templates.find((t) => t.id === selectedTemplateId) ?? null
	);

	let selectedBadge = $derived(
		selectedBadgeId ? (inventory.held_badges.find((b) => b.id === selectedBadgeId) ?? null) : null
	);

	// Mirror UserLink's nameStyle behavior: default/null falls back to inherited
	// color so the preview matches what renders in chat and on the leaderboard.
	function nameStyleFor(t: NameTemplateDef | null): string {
		if (!t || t.id === 'default') return '';
		const parts: string[] = [];
		if (t.gradient) {
			parts.push(
				`background: linear-gradient(90deg, ${t.gradient[0]}, ${t.gradient[1]});`,
				'-webkit-background-clip: text;',
				'background-clip: text;',
				'color: transparent;'
			);
		} else if (t.color) {
			parts.push(`color: ${t.color};`);
		}
		if (t.name_css) {
			parts.push(t.name_css);
		}
		return parts.join(' ');
	}
</script>

<div class="rewards-picker">
	<div
		class="preview"
		style={selectedTemplate?.background_css
			? `background: ${selectedTemplate.background_css};`
			: ''}
	>
		{#if user.twitch_avatar_url}
			<img src={user.twitch_avatar_url} alt="" class="preview-avatar" />
		{/if}
		<span class="preview-name" style={nameStyleFor(selectedTemplate)}>{displayName}</span>
		{#if selectedBadge}
			<img
				src="/badges/{selectedBadge.icon_filename}"
				alt={selectedBadge.name}
				class="preview-badge"
			/>
		{/if}
	</div>

	<div class="subsection">
		<span class="subsection-label">Badge</span>
		<p class="subsection-description">
			Choose a badge to display next to your name in races and on the leaderboard.
		</p>
		<div class="badge-grid">
			<button
				type="button"
				class="badge-tile"
				class:selected={selectedBadgeId === null}
				title="No badge"
				onclick={() => (selectedBadgeId = null)}
			>
				<span class="badge-tile-glyph" aria-hidden="true">🚫</span>
				<span class="badge-tile-name">None</span>
				{#if inventory.equipped_badge_id === null}
					<span class="active-pastille">Active</span>
				{/if}
			</button>
			{#each inventory.held_badges as badge (badge.id)}
				<button
					type="button"
					class="badge-tile"
					class:selected={selectedBadgeId === badge.id}
					title={rewards.lookupBadge(badge.id)?.description ?? badge.name}
					onclick={() => (selectedBadgeId = badge.id)}
				>
					<img src="/badges/{badge.icon_filename}" alt="" class="badge-tile-icon" />
					<span class="badge-tile-name">{badge.name}</span>
					{#if inventory.equipped_badge_id === badge.id}
						<span class="active-pastille">Active</span>
					{/if}
				</button>
			{/each}
		</div>
	</div>

	<div class="subsection">
		<span class="subsection-label">Name template</span>
		<p class="subsection-description">
			Choose a visual style for your username on the website and in-game leaderboards.
		</p>
		<ul class="template-list">
			{#each inventory.unlocked_templates as t (t.id)}
				{@const isActive = (inventory.equipped_name_template_id ?? 'default') === t.id}
				{@const description = rewards.lookupTemplate(t.id)?.description ?? null}
				<li>
					<button
						type="button"
						class="template-row"
						class:selected={selectedTemplateId === t.id}
						style={t.background_css ? `background: ${t.background_css};` : ''}
						onclick={() => (selectedTemplateId = t.id)}
					>
						<span class="template-text">
							<span class="template-name" style={nameStyleFor(t)}>{t.name}</span>
							{#if description}
								<span class="template-description">{description}</span>
							{/if}
						</span>
						{#if isActive}
							<span class="active-pastille">Active</span>
						{/if}
					</button>
				</li>
			{/each}
		</ul>
	</div>
</div>

<style>
	.rewards-picker {
		display: flex;
		flex-direction: column;
		gap: 1.25rem;
	}

	.preview {
		display: flex;
		align-items: center;
		gap: 0.5rem;
		padding: 0.75rem 1rem;
		background: var(--color-bg);
		border: 1px solid var(--color-border);
		border-radius: var(--radius-md);
		min-height: 3rem;
	}

	.preview-avatar {
		width: 28px;
		height: 28px;
		border-radius: 50%;
		object-fit: cover;
		flex-shrink: 0;
	}

	.preview-name {
		font-weight: 500;
		font-size: var(--font-size-base);
	}

	.preview-badge {
		width: 18px;
		height: 18px;
		flex-shrink: 0;
	}

	.subsection {
		display: flex;
		flex-direction: column;
	}

	.subsection-label {
		font-size: var(--font-size-base);
		font-weight: 500;
		margin-bottom: 0.25rem;
	}

	.subsection-description {
		color: var(--color-text-secondary);
		font-size: var(--font-size-xs);
		margin: 0 0 0.75rem;
	}

	.badge-grid {
		display: grid;
		grid-template-columns: repeat(2, 1fr);
		gap: 0.5rem;
	}

	.badge-tile {
		position: relative;
		display: flex;
		flex-direction: column;
		align-items: center;
		justify-content: center;
		gap: 0.4rem;
		padding: 0.75rem 0.5rem;
		min-height: 80px;
		background: var(--color-bg);
		border: 2px solid var(--color-border);
		border-radius: var(--radius-sm);
		color: var(--color-text);
		cursor: pointer;
		font: inherit;
		transition: border-color 120ms ease;
	}

	.badge-tile:hover {
		border-color: var(--color-text-disabled);
	}

	.badge-tile.selected {
		border-color: var(--color-purple);
	}

	.badge-tile-icon {
		width: 28px;
		height: 28px;
	}

	.badge-tile-glyph {
		font-size: 1.6rem;
		line-height: 1;
	}

	.badge-tile-name {
		font-size: var(--font-size-sm);
		text-align: center;
	}

	.template-list {
		list-style: none;
		padding: 0;
		margin: 0;
		display: flex;
		flex-direction: column;
		gap: 0.5rem;
	}

	.template-row {
		width: 100%;
		display: flex;
		align-items: center;
		gap: 0.75rem;
		padding: 0.5rem 0.75rem;
		background: var(--color-bg);
		border: 2px solid var(--color-border);
		border-radius: var(--radius-sm);
		color: var(--color-text);
		cursor: pointer;
		font: inherit;
		text-align: left;
		transition: border-color 120ms ease;
	}

	.template-row:hover {
		border-color: var(--color-text-disabled);
	}

	.template-row.selected {
		border-color: var(--color-purple);
	}

	.template-text {
		flex: 1;
		display: flex;
		flex-direction: column;
		gap: 0.15rem;
		min-width: 0;
	}

	.template-name {
		display: inline-block;
		align-self: flex-start;
		font-weight: 500;
		font-size: var(--font-size-base);
	}

	.template-description {
		font-size: var(--font-size-xs);
		color: var(--color-text-secondary);
		opacity: 0.9;
	}

	.active-pastille {
		font-size: var(--font-size-xs);
		color: var(--color-gold);
		flex-shrink: 0;
	}

	.badge-tile .active-pastille {
		position: absolute;
		top: 0.25rem;
		right: 0.4rem;
	}
</style>
