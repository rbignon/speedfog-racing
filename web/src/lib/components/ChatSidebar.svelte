<script lang="ts">
	import type { ChatMessage } from '$lib/websocket';
	import ChatPanel from './ChatPanel.svelte';

	interface Props {
		messages: ChatMessage[];
		canSend: boolean;
		collapsed: boolean;
		onSend: (message: string) => void;
		onToggle: () => void;
	}

	let {
		messages,
		canSend,
		collapsed,
		onSend,
		onToggle
	}: Props = $props();

	let lastSeenCount = $state(0);
	let unreadCount = $state(0);

	$effect(() => {
		if (!collapsed) {
			// Mark all as seen when sidebar is open
			lastSeenCount = messages.length;
			unreadCount = 0;
		} else {
			// Accumulate unread while collapsed
			const newCount = messages.length - lastSeenCount;
			unreadCount = newCount > 0 ? newCount : 0;
		}
	});
</script>

<aside class="chat-sidebar" class:collapsed>
	<button class="toggle-btn" onclick={onToggle} title={collapsed ? 'Open chat' : 'Close chat'}>
		{#if collapsed}
			<svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
			</svg>
			{#if unreadCount > 0}
				<span class="unread-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
			{/if}
		{:else}
			<svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<polyline points="13 6 19 12 13 18" />
				<line x1="7" y1="12" x2="19" y2="12" />
				<line x1="3" y1="4" x2="3" y2="20" />
			</svg>
		{/if}
	</button>

	{#if !collapsed}
		<div class="sidebar-content">
			<div class="chat-header">CHAT</div>
			<div class="chat-area">
				<ChatPanel {messages} {canSend} {onSend} />
			</div>
		</div>
	{/if}
</aside>

<style>
	.chat-sidebar {
		position: relative;
		width: 320px;
		flex-shrink: 0;
		background: var(--color-surface);
		border-left: 1px solid var(--color-border);
		display: flex;
		flex-direction: column;
		transition: width var(--transition);
		overflow: hidden;
	}

	.chat-sidebar.collapsed {
		width: 44px;
	}

	.toggle-btn {
		position: absolute;
		top: 0.5rem;
		left: 0;
		width: 44px;
		height: 44px;
		background: none;
		border: none;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-text-secondary);
		transition: color var(--transition);
		flex-shrink: 0;
		z-index: 1;
	}

	.toggle-btn:hover {
		color: var(--color-text);
	}

	.icon {
		flex-shrink: 0;
	}

	.unread-badge {
		position: absolute;
		top: 6px;
		right: 4px;
		min-width: 16px;
		height: 16px;
		background: var(--color-danger);
		color: #fff;
		font-size: 0.55rem;
		font-weight: 700;
		border-radius: 8px;
		display: flex;
		align-items: center;
		justify-content: center;
		padding: 0 3px;
		pointer-events: none;
	}

	.sidebar-content {
		display: flex;
		flex-direction: column;
		height: 100%;
		padding-top: 52px;
		min-height: 0;
	}

	.chat-header {
		padding: 0 0.75rem 0.5rem;
		font-size: var(--font-size-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
		flex-shrink: 0;
	}

	.chat-area {
		flex: 1;
		min-height: 0;
		display: flex;
		flex-direction: column;
	}

	@media (max-width: 768px) {
		.chat-sidebar {
			display: none;
		}
	}
</style>
