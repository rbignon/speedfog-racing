<script lang="ts">
	import type { ChatMessage } from '$lib/websocket';
	import ChatPanel from './ChatPanel.svelte';

	interface Props {
		messagesParticipants: ChatMessage[];
		messagesPublic: ChatMessage[];
		canSend: boolean;
		collapsed: boolean;
		showParticipants: boolean;
		publicEnabled: boolean;
		activeTab: 'participants' | 'public';
		historyVersion: number;
		onSend: (message: string, channel: 'participants' | 'public') => void;
		onToggle: () => void;
		onTabChange: (tab: 'participants' | 'public') => void;
	}

	let {
		messagesParticipants,
		messagesPublic,
		canSend,
		collapsed,
		showParticipants,
		publicEnabled,
		activeTab,
		historyVersion,
		onSend,
		onToggle,
		onTabChange
	}: Props = $props();

	let lastSeenCount = $state(0);
	let unreadCount = $state(0);
	let unreadParticipants = $state(0);
	let unreadPublic = $state(0);
	let lastSeenParticipants = $state(0);
	let lastSeenPublic = $state(0);

	let activeMessages = $derived(
		activeTab === 'participants' ? messagesParticipants : messagesPublic
	);

	// When chat history is loaded (initial connect or reconnect), treat all messages as seen
	let lastHistoryVersion = $state(0);
	$effect(() => {
		if (historyVersion !== lastHistoryVersion) {
			lastSeenParticipants = messagesParticipants.length;
			lastSeenPublic = messagesPublic.length;
			lastSeenCount = messagesParticipants.length + messagesPublic.length;
			lastHistoryVersion = historyVersion;
		}
	});

	// Track unread for collapsed state
	$effect(() => {
		const total = messagesParticipants.length + messagesPublic.length;
		if (!collapsed) {
			lastSeenCount = total;
			unreadCount = 0;
		} else {
			const newCount = total - lastSeenCount;
			unreadCount = newCount > 0 ? newCount : 0;
		}
	});

	// Track per-tab unread
	$effect(() => {
		if (activeTab === 'participants' && !collapsed) {
			lastSeenParticipants = messagesParticipants.length;
			unreadParticipants = 0;
		} else {
			const diff = messagesParticipants.length - lastSeenParticipants;
			unreadParticipants = diff > 0 ? diff : 0;
		}
	});

	$effect(() => {
		if (activeTab === 'public' && !collapsed) {
			lastSeenPublic = messagesPublic.length;
			unreadPublic = 0;
		} else {
			const diff = messagesPublic.length - lastSeenPublic;
			unreadPublic = diff > 0 ? diff : 0;
		}
	});

	function handleSend(message: string) {
		onSend(message, activeTab);
	}
</script>

<aside class="chat-sidebar" class:collapsed>
	{#if collapsed}
		<button class="toggle-btn" onclick={onToggle} title="Open chat">
			<svg
				class="icon"
				width="18"
				height="18"
				viewBox="0 0 24 24"
				fill="none"
				stroke="currentColor"
				stroke-width="2"
				stroke-linecap="round"
				stroke-linejoin="round"
			>
				<path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
			</svg>
			{#if unreadCount > 0}
				<span class="unread-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
			{/if}
		</button>
	{:else}
		<div class="sidebar-content">
			<div class="chat-header">
				{#if showParticipants}
					<div class="tab-bar">
						<button
							class="tab"
							class:active={activeTab === 'participants'}
							onclick={() => onTabChange('participants')}
						>
							Participants
							{#if unreadParticipants > 0 && activeTab !== 'participants'}
								<span class="tab-badge"
									>{unreadParticipants > 99 ? '99+' : unreadParticipants}</span
								>
							{/if}
						</button>
						<button
							class="tab"
							class:active={activeTab === 'public'}
							class:disabled={!publicEnabled}
							disabled={!publicEnabled}
							onclick={() => publicEnabled && onTabChange('public')}
							title={!publicEnabled ? 'Available after finishing the race' : ''}
						>
							Public
							{#if unreadPublic > 0 && activeTab !== 'public'}
								<span class="tab-badge"
									>{unreadPublic > 99 ? '99+' : unreadPublic}</span
								>
							{/if}
						</button>
					</div>
				{:else}
					<span class="chat-title">Chat</span>
				{/if}
				<button class="collapse-btn" onclick={onToggle} title="Close chat">
					<svg
						width="16"
						height="16"
						viewBox="0 0 24 24"
						fill="none"
						stroke="currentColor"
						stroke-width="2"
						stroke-linecap="round"
						stroke-linejoin="round"
					>
						<polyline points="13 6 19 12 13 18" />
						<line x1="7" y1="12" x2="19" y2="12" />
						<line x1="3" y1="4" x2="3" y2="20" />
					</svg>
				</button>
			</div>
			<div class="chat-area">
				<ChatPanel messages={activeMessages} {canSend} onSend={handleSend} />
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
		padding: 0 0.5rem 0 0;
		border-bottom: 1px solid var(--color-border);
		flex-shrink: 0;
		min-height: 42px;
	}

	.chat-title {
		font-size: var(--font-size-sm);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.05em;
		color: var(--color-text-secondary);
		padding: 0 0.75rem;
	}

	.tab-bar {
		display: flex;
		gap: 0;
		flex: 1;
	}

	.tab {
		flex: 1;
		padding: 0.6rem 0.5rem;
		background: none;
		border: none;
		border-bottom: 2px solid transparent;
		cursor: pointer;
		font-size: var(--font-size-xs);
		font-weight: 600;
		text-transform: uppercase;
		letter-spacing: 0.04em;
		color: var(--color-text-secondary);
		transition:
			color var(--transition),
			border-color var(--transition);
		position: relative;
	}

	.tab:hover:not(.disabled) {
		color: var(--color-text);
	}

	.tab.active {
		color: var(--color-primary);
		border-bottom-color: var(--color-primary);
	}

	.tab.disabled {
		opacity: 0.35;
		cursor: not-allowed;
	}

	.tab-badge {
		display: inline-flex;
		align-items: center;
		justify-content: center;
		min-width: 14px;
		height: 14px;
		background: var(--color-danger);
		color: #fff;
		font-size: 0.5rem;
		font-weight: 700;
		border-radius: 7px;
		padding: 0 3px;
		margin-left: 4px;
		vertical-align: middle;
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
		flex-shrink: 0;
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
