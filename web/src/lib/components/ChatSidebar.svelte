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
	{#if collapsed}
		<button class="toggle-btn" onclick={onToggle} title="Open chat">
			<svg class="icon" width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
				<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
			</svg>
			{#if unreadCount > 0}
				<span class="unread-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
			{/if}
		</button>
	{:else}
		<div class="sidebar-content">
			<div class="chat-header">
				<span class="chat-title">Chat</span>
				<button class="collapse-btn" onclick={onToggle} title="Close chat">
					<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
						<polyline points="13 6 19 12 13 18" />
						<line x1="7" y1="12" x2="19" y2="12" />
						<line x1="3" y1="4" x2="3" y2="20" />
					</svg>
				</button>
			</div>
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
		width: 44px;
		height: 44px;
		margin: 0.5rem auto 0;
		background: none;
		border: none;
		cursor: pointer;
		display: flex;
		align-items: center;
		justify-content: center;
		color: var(--color-text-secondary);
		transition: color var(--transition);
		position: relative;
	}

	.toggle-btn:hover {
		color: var(--color-text);
	}

	.icon {
		flex-shrink: 0;
	}

	.unread-badge {
		position: absolute;
		top: 2px;
		right: 2px;
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
		min-height: 0;
	}

	.chat-header {
		display: flex;
		align-items: center;
		justify-content: space-between;
		padding: 0.75rem;
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
	}

	.chat-title {
		font-size: var(--font-size-sm);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
	}

	.collapse-btn {
		background: none;
		border: none;
		cursor: pointer;
		color: var(--color-text-secondary);
		display: flex;
		align-items: center;
		padding: 0.25rem;
		border-radius: var(--radius-sm);
		transition: color var(--transition);
	}

	.collapse-btn:hover {
		color: var(--color-text);
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
