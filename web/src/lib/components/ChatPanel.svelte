<script lang="ts">
  import { untrack } from "svelte";
  import type { ChatMessage } from "$lib/websocket";
  import { rewards } from "$lib/stores/rewards.svelte";

  interface Props {
    messages: ChatMessage[];
    canSend: boolean;
    currentUsername?: string | null;
    channel?: string;
    historyVersion?: number;
    onSend: (message: string, replyTo?: string) => void;
    onReact?: (messageId: string, emoji: string) => void;
  }

  let {
    messages,
    canSend,
    currentUsername = null,
    channel = "participants",
    historyVersion = 0,
    onSend,
    onReact = () => {},
  }: Props = $props();

  function templateFor(msg: ChatMessage) {
    const id = msg.equipped_name_template_id;
    if (!id || id === "default") return null;
    return rewards.lookupTemplate(id);
  }

  function nameStyleFor(msg: ChatMessage): string {
    const t = templateFor(msg);
    const parts: string[] = [];
    if (t?.gradient) {
      parts.push(
        `background: linear-gradient(90deg, ${t.gradient[0]}, ${t.gradient[1]});`,
        "-webkit-background-clip: text;",
        "background-clip: text;",
        "color: transparent;",
        "padding-inline-end: 0.1em;",
      );
    } else if (t?.color) {
      parts.push(`color: ${t.color};`);
    }
    if (t?.name_css) {
      parts.push(t.name_css);
    }
    return parts.join(" ");
  }

  const TRAIT_META: Record<
    string,
    { icon: string; color: string; label: string }
  > = {
    rusher: { icon: "\u26A1", color: "#DC6A51", label: "Rusher" },
    cautious: {
      icon: "\uD83D\uDEE1\uFE0F",
      color: "#4AAE8C",
      label: "Cautious",
    },
    boss_slayer: {
      icon: "\u2694\uFE0F",
      color: "#C8A44E",
      label: "Boss Slayer",
    },
    resilient: { icon: "\uD83D\uDCAA", color: "#7BA2CC", label: "Resilient" },
    explorer: { icon: "\uD83C\uDF10", color: "#7BA2CC", label: "Explorer" },
    pathfinder: { icon: "\uD83E\uDDED", color: "#A99BC9", label: "Pathfinder" },
    rage_quitter: {
      icon: "\uD83D\uDCA5",
      color: "#B5462F",
      label: "Rage Quitter",
    },
  };

  const REACTION_EMOJIS: { code: string; glyph: string }[] = [
    { code: "thumbs_up", glyph: "\u{1F44D}" },
    { code: "thumbs_down", glyph: "\u{1F44E}" },
    { code: "laugh", glyph: "\u{1F602}" },
    { code: "cry", glyph: "\u{1F622}" },
  ];
  const EMOJI_GLYPHS: Record<string, string> = Object.fromEntries(
    REACTION_EMOJIS.map((e) => [e.code, e.glyph]),
  );

  let inputValue = $state("");
  let replyTarget = $state<ChatMessage | null>(null);
  let listEl = $state<HTMLElement | null>(null);
  let inputEl = $state<HTMLInputElement | null>(null);

  function startReply(msg: ChatMessage) {
    replyTarget = msg;
    // The input is always rendered when the reply button is (both gated
    // by canSend), so it can take focus immediately.
    inputEl?.focus();
  }

  function scrollToMessage(id: string) {
    const el = listEl?.querySelector<HTMLElement>(`[data-msg-id="${id}"]`);
    if (!el) return;
    el.scrollIntoView({ behavior: "smooth", block: "center" });
    el.classList.add("flash");
    setTimeout(() => el.classList.remove("flash"), 1500);
  }

  // Stick to the bottom only while the viewer is already there; otherwise
  // accumulate a "new messages" count for the jump pill. System messages
  // are ambient and never counted (same rule as the unread badges).
  let atBottom = $state(true);
  let pendingCount = $state(0);
  let prevNotifyCount = 0; // not reactive: last non-system count seen

  function notifyCountOf(list: ChatMessage[]): number {
    return list.reduce((n, m) => (m.role === "system" ? n : n + 1), 0);
  }

  function scrollToBottom() {
    // Use requestAnimationFrame so the new DOM node is painted first
    requestAnimationFrame(() => {
      if (listEl) {
        listEl.scrollTop = listEl.scrollHeight;
      }
    });
  }

  function jumpToLatest() {
    atBottom = true;
    pendingCount = 0;
    scrollToBottom();
  }

  function handleScroll() {
    if (!listEl) return;
    atBottom =
      listEl.scrollHeight - listEl.scrollTop - listEl.clientHeight < 40;
    if (atBottom) pendingCount = 0;
  }

  $effect(() => {
    const notifyCount = notifyCountOf(messages);
    const added = notifyCount - prevNotifyCount;
    prevNotifyCount = notifyCount;
    void messages.length; // system messages also grow the list
    if (atBottom) {
      scrollToBottom();
    } else if (added > 0) {
      pendingCount += added;
    }
  });

  // History (re)loads and tab switches always reset to the bottom.
  // untrack: reading messages here must not make this effect re-run on
  // every new message, or it would defeat the anchor above.
  $effect(() => {
    void channel;
    void historyVersion;
    atBottom = true;
    pendingCount = 0;
    prevNotifyCount = untrack(() => notifyCountOf(messages));
    scrollToBottom();
  });

  function formatTime(timestamp: string): string {
    const d = new Date(timestamp);
    return d.toLocaleTimeString(undefined, {
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  function submitInput() {
    const text = inputValue.trim();
    if (!text) return;
    onSend(text, replyTarget?.id ?? undefined);
    inputValue = "";
    replyTarget = null;
  }

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    submitInput();
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      replyTarget = null;
      return;
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submitInput();
    }
  }
</script>

<div class="chat-panel">
  <div class="list-wrap">
    <div class="message-list" bind:this={listEl} onscroll={handleScroll}>
      {#if messages.length === 0}
        <p class="empty">No messages yet</p>
      {:else}
        {#each messages as msg, i (msg.id ?? msg.timestamp + msg.username + i)}
          {#if msg.role === "system"}
            <div class="system-message">
              <span class="system-text">{msg.message}</span>
              <span class="timestamp">{formatTime(msg.timestamp)}</span>
            </div>
          {:else}
            {@const badge = rewards.lookupBadge(msg.equipped_badge_id)}
            {@const msgId = msg.id ?? null}
            <div class="message" data-msg-id={msgId}>
              {#if canSend && msgId}
                <div class="msg-actions">
                  {#each REACTION_EMOJIS as e (e.code)}
                    <button
                      type="button"
                      class="action-btn"
                      title={e.code.replace("_", " ")}
                      onclick={() => onReact(msgId, e.code)}>{e.glyph}</button
                    >
                  {/each}
                  <button
                    type="button"
                    class="action-btn action-reply"
                    title="Reply"
                    onclick={() => startReply(msg)}>&#8617;</button
                  >
                </div>
              {/if}
              <div class="message-header">
                {#if msg.avatar_url}
                  <img src={msg.avatar_url} alt="" class="avatar" />
                {:else}
                  <div class="avatar-placeholder"></div>
                {/if}
                <div class="meta">
                  <a
                    href="/user/{msg.username}"
                    target="_blank"
                    rel="noopener noreferrer"
                    class="display-name"
                    style={nameStyleFor(msg)}
                    >{msg.display_name ?? msg.username}</a
                  >
                  {#if badge}
                    <img
                      src="/badges/{badge.icon_filename}"
                      alt={badge.name}
                      title={badge.name}
                      class="reward-badge"
                    />
                  {/if}
                  {#if msg.role === "organizer"}
                    <span class="badge badge-organizer">ORG</span>
                  {:else if msg.role === "caster"}
                    <span class="badge badge-caster">CAST</span>
                  {/if}
                  {#if msg.dominant_trait && TRAIT_META[msg.dominant_trait]}
                    {@const trait = TRAIT_META[msg.dominant_trait]}
                    <span
                      class="badge badge-trait"
                      style="background: {trait.color}20; color: {trait.color}"
                      title={trait.label}
                      aria-label={trait.label}>{trait.icon}</span
                    >
                  {/if}
                  <span class="timestamp">{formatTime(msg.timestamp)}</span>
                </div>
              </div>
              {#if msg.reply_to}
                {@const quote = msg.reply_to}
                <button
                  type="button"
                  class="reply-quote"
                  onclick={() => scrollToMessage(quote.id)}
                >
                  <span class="reply-author"
                    >{quote.display_name ?? quote.username}</span
                  >
                  <span class="reply-snippet">{quote.snippet}</span>
                </button>
              {/if}
              <p class="message-text">{msg.message}</p>
              {#if msg.reactions?.length}
                <div class="reaction-row">
                  {#each msg.reactions as r (r.emoji)}
                    <button
                      type="button"
                      class="reaction-pill"
                      class:mine={currentUsername !== null &&
                        r.usernames.includes(currentUsername)}
                      title={r.usernames.join(", ")}
                      disabled={!canSend || !msgId}
                      onclick={() => msgId && onReact(msgId, r.emoji)}
                      >{EMOJI_GLYPHS[r.emoji] ?? r.emoji}
                      {r.usernames.length}</button
                    >
                  {/each}
                </div>
              {/if}
            </div>
          {/if}
        {/each}
      {/if}
    </div>
    {#if pendingCount > 0 && !atBottom}
      <button type="button" class="new-messages-pill" onclick={jumpToLatest}>
        &darr; {pendingCount} new {pendingCount === 1 ? "message" : "messages"}
      </button>
    {/if}
  </div>
  {#if canSend && replyTarget}
    <div class="reply-bar">
      <span class="reply-bar-text"
        >Replying to {replyTarget.display_name ?? replyTarget.username}</span
      >
      <button
        type="button"
        class="reply-cancel"
        title="Cancel reply"
        onclick={() => (replyTarget = null)}>&#10005;</button
      >
    </div>
  {/if}
  {#if canSend}
    <form class="input-row" onsubmit={handleSubmit}>
      <input
        type="text"
        class="chat-input"
        placeholder="Send a message..."
        maxlength={500}
        bind:this={inputEl}
        bind:value={inputValue}
        onkeydown={handleKeydown}
      />
      <button type="submit" class="send-btn" disabled={!inputValue.trim()}
        >Send</button
      >
    </form>
  {/if}
</div>

<style>
  .chat-panel {
    display: flex;
    flex-direction: column;
    height: 100%;
    min-height: 0;
  }

  .list-wrap {
    position: relative;
    flex: 1;
    min-height: 0;
    display: flex;
    flex-direction: column;
  }

  .message-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 0.75rem;
    min-height: 0;
  }

  .new-messages-pill {
    position: absolute;
    bottom: 0.5rem;
    left: 50%;
    transform: translateX(-50%);
    background: var(--color-purple);
    color: var(--color-ink-on-accent);
    border: none;
    border-radius: var(--radius-md);
    font-family: var(--font-family);
    font-size: var(--font-size-xs);
    font-weight: 600;
    padding: 0.25rem 0.75rem;
    cursor: pointer;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.35);
    white-space: nowrap;
  }

  .new-messages-pill:hover {
    background: var(--color-purple-hover);
  }

  .empty {
    color: var(--color-text-disabled);
    font-size: var(--font-size-sm);
    font-style: italic;
    text-align: center;
    margin: auto;
  }

  .system-message {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 0.6rem;
    padding: 0.25rem 0;
  }

  .system-text {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--color-text-secondary);
  }

  .message {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    position: relative;
  }

  .msg-actions {
    position: absolute;
    top: -0.4rem;
    right: 0.25rem;
    display: flex;
    gap: 0.1rem;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.1rem;
    z-index: 1;
    opacity: 0;
    pointer-events: none;
    transition: opacity var(--transition);
  }

  /* display:none would drop these buttons from the tab order entirely, so
     keep them laid out and gate visibility with opacity instead: hidden by
     default, revealed on hover, and reachable (and revealed) via keyboard
     focus. */
  .message:hover .msg-actions,
  .message:focus-within .msg-actions {
    opacity: 1;
    pointer-events: auto;
  }

  .action-btn {
    background: none;
    border: none;
    cursor: pointer;
    font-size: 0.85rem;
    line-height: 1;
    padding: 0.15rem 0.25rem;
    border-radius: var(--radius-sm);
    color: var(--color-text-secondary);
  }

  .action-btn:hover {
    background: var(--color-border);
  }

  .reply-quote {
    display: flex;
    gap: 0.35rem;
    align-items: baseline;
    margin-left: calc(24px + 0.5rem);
    padding: 0.1rem 0.4rem;
    background: none;
    border: none;
    border-left: 2px solid var(--color-border);
    cursor: pointer;
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-align: left;
    min-width: 0;
  }

  .reply-quote:hover {
    color: var(--color-text);
  }

  .reply-author {
    font-weight: 600;
    flex-shrink: 0;
  }

  .reply-snippet {
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .reaction-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.25rem;
    padding-left: calc(24px + 0.5rem);
  }

  .reaction-pill {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    background: none;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.05rem 0.45rem;
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    cursor: pointer;
    transition: border-color var(--transition);
  }

  .reaction-pill:hover:not(:disabled) {
    border-color: var(--color-purple);
  }

  .reaction-pill:disabled {
    cursor: default;
  }

  .reaction-pill.mine {
    border-color: var(--color-purple);
    background: rgba(169, 155, 201, 0.12);
  }

  .reply-bar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
    padding: 0.3rem 0.75rem;
    border-top: 1px solid var(--color-border);
    background: var(--color-surface-elevated);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    flex-shrink: 0;
  }

  .reply-cancel {
    background: none;
    border: none;
    cursor: pointer;
    color: var(--color-text-secondary);
    padding: 0.1rem 0.25rem;
  }

  .reply-cancel:hover {
    color: var(--color-text);
  }

  :global(.message.flash) {
    animation: chat-flash 1.5s ease-out;
  }

  @keyframes chat-flash {
    0% {
      background: rgba(169, 155, 201, 0.25);
    }
    100% {
      background: transparent;
    }
  }

  .message-header {
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

  .meta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.3rem;
    min-width: 0;
  }

  .badge {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    font-weight: 500;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    padding: 0 0.28rem;
    border: 1px solid transparent;
    border-radius: var(--radius-sm);
  }

  .badge-organizer {
    border-color: rgba(200, 164, 78, 0.4);
    color: var(--color-gold);
  }

  .badge-caster {
    border-color: rgba(220, 106, 81, 0.4);
    color: var(--color-danger);
  }

  .badge-trait {
    font-size: 0.7rem;
  }

  .reward-badge {
    width: 14px;
    height: 14px;
    flex-shrink: 0;
  }

  .display-name {
    font-size: var(--font-size-sm);
    font-weight: 600;
    color: var(--color-text);
    text-decoration: none;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    min-width: 0;
  }

  .display-name:hover {
    color: var(--color-purple-hover);
  }

  /* One grey step below the message/system text, so the metadata reads as
   * a different layer than the content. */
  .timestamp {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    color: var(--color-text-disabled);
    flex-shrink: 0;
  }

  .message-text {
    margin: 0;
    padding-left: calc(24px + 0.5rem);
    font-size: var(--font-size-sm);
    color: var(--color-text);
    word-break: break-word;
    line-height: 1.4;
  }

  .input-row {
    display: flex;
    gap: 0.5rem;
    padding: 0.75rem;
    border-top: 1px solid var(--color-border);
    flex-shrink: 0;
  }

  .chat-input {
    flex: 1;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    padding: 0.4rem 0.6rem;
    min-width: 0;
    outline: none;
    transition: border-color var(--transition);
  }

  .chat-input:focus {
    border-color: var(--color-purple);
    box-shadow: 0 0 0 1px var(--color-purple);
  }

  .chat-input::placeholder {
    color: var(--color-text-disabled);
  }

  .send-btn {
    background: var(--color-gold);
    color: var(--color-ink-on-accent);
    border: none;
    border-radius: var(--radius-md);
    font-family: var(--font-display);
    font-weight: 600;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    padding: 0.4rem 0.75rem;
    cursor: pointer;
    transition: background var(--transition);
    flex-shrink: 0;
  }

  .send-btn:hover:not(:disabled) {
    background: var(--color-gold-hover);
  }

  .send-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
