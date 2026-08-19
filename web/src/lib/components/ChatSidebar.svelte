<script lang="ts">
  import {
    chatSidebarLayout,
    type ChatTab,
    type PublicAccess,
  } from "$lib/chat-sidebar-layout";
  import type { ChatMessage } from "$lib/websocket";
  import ChatPanel from "./ChatPanel.svelte";
  import ZoneSheet from "./ZoneSheet.svelte";

  interface Props {
    messagesParticipants: ChatMessage[];
    messagesPublic: ChatMessage[];
    canSend: boolean;
    currentUsername: string | null;
    collapsed: boolean;
    participantsAccess: boolean;
    publicAccess: PublicAccess;
    publicLockedReason?: string;
    showPublicOnly?: boolean;
    activeTab: ChatTab;
    historyVersion: number;
    onSend: (message: string, channel: ChatTab, replyTo?: string) => void;
    onReact: (messageId: string, emoji: string, channel: ChatTab) => void;
    onToggle: () => void;
    onTabChange: (tab: ChatTab) => void;
    zoneSheet?: { nodeId: string; displayName: string; zones: string[] } | null;
    onZoneSheetClose?: () => void;
  }

  let {
    messagesParticipants,
    messagesPublic,
    canSend,
    currentUsername,
    collapsed,
    participantsAccess,
    publicAccess,
    publicLockedReason,
    showPublicOnly = false,
    activeTab,
    historyVersion,
    onSend,
    onReact,
    onToggle,
    onTabChange,
    zoneSheet = null,
    onZoneSheetClose = () => {},
  }: Props = $props();

  let layout = $derived(
    chatSidebarLayout({
      publicAccess,
      participantsAccess,
      showPublicOnly,
      activeTab,
    }),
  );

  let lastSeenCount = $state(0);
  let unreadCount = $state(0);
  let unreadParticipants = $state(0);
  let unreadPublic = $state(0);
  let lastSeenParticipants = $state(0);
  let lastSeenPublic = $state(0);

  let activeMessages = $derived(
    layout.effectiveTab === "participants"
      ? messagesParticipants
      : messagesPublic,
  );

  // System messages (joins, starts, finishes, etc.) should not raise the
  // unread badge: they are ambient context, not chat the user must read.
  let participantsNotifyCount = $derived(
    messagesParticipants.reduce((n, m) => (m.role === "system" ? n : n + 1), 0),
  );
  let publicNotifyCount = $derived(
    messagesPublic.reduce((n, m) => (m.role === "system" ? n : n + 1), 0),
  );

  // When chat history is loaded (initial connect, reconnect, or pull
  // after access unlock), treat all messages as seen so the badge does
  // not jump.
  let lastHistoryVersion = $state(0);
  $effect(() => {
    if (historyVersion !== lastHistoryVersion) {
      lastSeenParticipants = participantsNotifyCount;
      lastSeenPublic = publicNotifyCount;
      lastSeenCount = participantsNotifyCount + publicNotifyCount;
      lastHistoryVersion = historyVersion;
    }
  });

  // Track unread for collapsed state. The chat is only actually "seen"
  // when the sidebar is expanded AND the zone codex sheet isn't covering
  // the tabs; otherwise treat it the same as collapsed so the badge keeps
  // accruing while a different view occupies the rail.
  $effect(() => {
    const total = participantsNotifyCount + publicNotifyCount;
    if (!collapsed && !zoneSheet) {
      lastSeenCount = total;
      unreadCount = 0;
    } else {
      const newCount = total - lastSeenCount;
      unreadCount = newCount > 0 ? newCount : 0;
    }
  });

  // Track per-tab unread
  $effect(() => {
    if (layout.effectiveTab === "participants" && !collapsed && !zoneSheet) {
      lastSeenParticipants = participantsNotifyCount;
      unreadParticipants = 0;
    } else {
      const diff = participantsNotifyCount - lastSeenParticipants;
      unreadParticipants = diff > 0 ? diff : 0;
    }
  });

  $effect(() => {
    if (
      layout.effectiveTab === "public" &&
      !collapsed &&
      !zoneSheet &&
      !layout.showLockedPane
    ) {
      lastSeenPublic = publicNotifyCount;
      unreadPublic = 0;
    } else {
      const diff = publicNotifyCount - lastSeenPublic;
      unreadPublic = diff > 0 ? diff : 0;
    }
  });

  function handleSend(message: string, replyTo?: string) {
    onSend(message, layout.effectiveTab, replyTo);
  }

  function handleReact(messageId: string, emoji: string) {
    onReact(messageId, emoji, layout.effectiveTab);
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
        <span class="unread-badge"
          >{unreadCount > 99 ? "99+" : unreadCount}</span
        >
      {/if}
    </button>
  {:else}
    <div class="sidebar-content">
      {#if zoneSheet}
        <div class="chat-header">
          <button class="tab back-btn" onclick={onZoneSheetClose}>
            Back to chat
            {#if unreadCount > 0}
              <span class="tab-badge"
                >{unreadCount > 99 ? "99+" : unreadCount}</span
              >
            {/if}
          </button>
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
          <ZoneSheet
            nodeId={zoneSheet.nodeId}
            displayName={zoneSheet.displayName}
            zones={zoneSheet.zones}
            onClose={onZoneSheetClose}
          />
        </div>
      {:else}
        <div class="chat-header">
          {#if layout.showTabs}
            <div class="tab-bar">
              <button
                class="tab"
                class:active={layout.effectiveTab === "participants"}
                onclick={() => onTabChange("participants")}
              >
                Participants
                {#if unreadParticipants > 0 && layout.effectiveTab !== "participants"}
                  <span class="tab-badge"
                    >{unreadParticipants > 99
                      ? "99+"
                      : unreadParticipants}</span
                  >
                {/if}
              </button>
              <button
                class="tab"
                class:active={layout.effectiveTab === "public"}
                class:disabled={layout.publicTabDisabled}
                disabled={layout.publicTabDisabled}
                onclick={() =>
                  !layout.publicTabDisabled && onTabChange("public")}
                title={layout.publicTabDisabled
                  ? (publicLockedReason ?? "Public chat is locked.")
                  : ""}
              >
                Spoilers
                {#if unreadPublic > 0 && layout.effectiveTab !== "public" && !layout.publicTabDisabled}
                  <span class="tab-badge"
                    >{unreadPublic > 99 ? "99+" : unreadPublic}</span
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
        {#if layout.showTabs && !layout.showLockedPane}
          <div class="channel-hint">
            {#if layout.effectiveTab === "participants"}
              Private chat between participants. Avoid sharing spoilers here.
            {:else}
              Open discussion, spoilers allowed. Visible to everyone except
              racers who haven't finished yet.
            {/if}
          </div>
        {/if}
        <div class="chat-area">
          {#if layout.showLockedPane}
            <div class="locked-pane">
              <svg
                class="lock-icon"
                width="32"
                height="32"
                viewBox="0 0 24 24"
                fill="none"
                stroke="currentColor"
                stroke-width="1.6"
                stroke-linecap="round"
                stroke-linejoin="round"
                aria-hidden="true"
              >
                <rect x="3" y="11" width="18" height="11" rx="2" ry="2" />
                <path d="M7 11V7a5 5 0 0 1 10 0v4" />
              </svg>
              <p>{publicLockedReason ?? "Public chat is locked."}</p>
            </div>
          {:else}
            <ChatPanel
              messages={activeMessages}
              {canSend}
              {currentUsername}
              channel={layout.effectiveTab}
              {historyVersion}
              onSend={handleSend}
              onReact={handleReact}
            />
          {/if}
        </div>
      {/if}
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
    font-family: var(--font-display);
    font-size: var(--font-size-base);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.09em;
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
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.09em;
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
    color: var(--color-text);
    border-bottom-color: var(--color-gold);
  }

  .tab.disabled {
    opacity: 0.35;
    cursor: not-allowed;
  }

  .back-btn {
    flex: initial;
    display: flex;
    align-items: center;
    gap: 0.3rem;
    padding: 0.6rem 0.75rem;
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

  .channel-hint {
    padding: 0.35rem 0.75rem;
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    background: var(--color-surface-elevated);
    border-bottom: 1px solid var(--color-border);
    line-height: 1.35;
    flex-shrink: 0;
  }

  .chat-area {
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .locked-pane {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 0.75rem;
    padding: 1.5rem 1.25rem;
    text-align: center;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    line-height: 1.4;
  }

  .lock-icon {
    opacity: 0.55;
  }

  .locked-pane p {
    margin: 0;
    max-width: 22ch;
  }

  @media (max-width: 768px) {
    .chat-sidebar {
      display: none;
    }
  }
</style>
