<script lang="ts">
  import type { ChatMessage } from "$lib/websocket";
  import { rewards } from "$lib/stores/rewards.svelte";

  interface Props {
    messages: ChatMessage[];
    canSend: boolean;
    onSend: (message: string) => void;
  }

  let { messages, canSend, onSend }: Props = $props();

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
      );
    } else if (t?.color) {
      parts.push(`color: ${t.color};`);
    }
    if (t?.name_css) {
      parts.push(t.name_css);
    }
    return parts.join(" ");
  }

  const TRAIT_META: Record<string, { icon: string; color: string; label: string }> = {
    rusher: { icon: "\u26A1", color: "#EF4444", label: "Rusher" },
    cautious: { icon: "\uD83D\uDEE1\uFE0F", color: "#10B981", label: "Cautious" },
    boss_slayer: { icon: "\u2694\uFE0F", color: "#FBBF24", label: "Boss Slayer" },
    resilient: { icon: "\uD83D\uDCAA", color: "#C8A44E", label: "Resilient" },
    explorer: { icon: "\uD83C\uDF10", color: "#3B82F6", label: "Explorer" },
    pathfinder: { icon: "\uD83E\uDDED", color: "#A78BFA", label: "Pathfinder" },
    rage_quitter: { icon: "\uD83D\uDCA5", color: "#DC2626", label: "Rage Quitter" },
  };

  let inputValue = $state("");
  let listEl = $state<HTMLElement | null>(null);

  $effect(() => {
    // Trigger scroll when messages change
    const _ = messages.length;
    if (listEl) {
      // Use requestAnimationFrame so the new DOM node is painted first
      requestAnimationFrame(() => {
        if (listEl) {
          listEl.scrollTop = listEl.scrollHeight;
        }
      });
    }
  });

  function formatTime(timestamp: string): string {
    const d = new Date(timestamp);
    return d.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
  }

  function handleSubmit(e: SubmitEvent) {
    e.preventDefault();
    const text = inputValue.trim();
    if (!text) return;
    onSend(text);
    inputValue = "";
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      const text = inputValue.trim();
      if (!text) return;
      onSend(text);
      inputValue = "";
    }
  }
</script>

<div class="chat-panel">
  <div class="message-list" bind:this={listEl}>
    {#if messages.length === 0}
      <p class="empty">No messages yet</p>
    {:else}
      {#each messages as msg, i (msg.timestamp + msg.username + i)}
        {#if msg.role === "system"}
          <div class="system-message">
            <span class="system-text">{msg.message}</span>
            <span class="timestamp">{formatTime(msg.timestamp)}</span>
          </div>
        {:else}
          {@const badge = rewards.lookupBadge(msg.equipped_badge_id)}
          <div class="message">
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
                  style={nameStyleFor(msg)}>{msg.display_name ?? msg.username}</a
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
            <p class="message-text">{msg.message}</p>
          </div>
        {/if}
      {/each}
    {/if}
  </div>
  {#if canSend}
    <form class="input-row" onsubmit={handleSubmit}>
      <input
        type="text"
        class="chat-input"
        placeholder="Send a message..."
        maxlength={500}
        bind:value={inputValue}
        onkeydown={handleKeydown}
      />
      <button type="submit" class="send-btn" disabled={!inputValue.trim()}>Send</button>
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

  .message-list {
    flex: 1;
    overflow-y: auto;
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    padding: 0.75rem;
    min-height: 0;
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
    align-items: center;
    gap: 0.5rem;
    padding: 0.25rem 0;
  }

  .system-text {
    font-size: var(--font-size-sm);
    font-style: italic;
    color: var(--color-text-secondary);
  }

  .message {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
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
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    padding: 0.1rem 0.3rem;
    border-radius: 3px;
  }

  .badge-organizer {
    background: rgba(200, 164, 78, 0.2);
    color: var(--color-gold);
  }

  .badge-caster {
    background: rgba(239, 68, 68, 0.15);
    color: #f87171;
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

  .timestamp {
    font-size: var(--font-size-xs);
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
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
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
  }

  .chat-input::placeholder {
    color: var(--color-text-disabled);
  }

  .send-btn {
    background: var(--color-purple);
    color: #fff;
    border: none;
    border-radius: var(--radius-sm);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 600;
    padding: 0.4rem 0.75rem;
    cursor: pointer;
    transition: background var(--transition);
    flex-shrink: 0;
  }

  .send-btn:hover:not(:disabled) {
    background: var(--color-purple-hover);
  }

  .send-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
