<script lang="ts">
  // Site-wide notice fed by the ANNOUNCEMENT server setting. Dismissal is
  // remembered per message text, so a new announcement shows up again for
  // everyone while the previous one stays hidden.
  let { text, url }: { text: string | null; url: string | null } = $props();

  const DISMISSED_KEY = "speedfog_announcement_dismissed";
  let dismissedText = $state(
    typeof localStorage !== "undefined"
      ? localStorage.getItem(DISMISSED_KEY)
      : null,
  );

  let visible = $derived(text !== null && text !== dismissedText);

  function dismiss() {
    dismissedText = text;
    if (text !== null) localStorage.setItem(DISMISSED_KEY, text);
  }
</script>

{#if visible}
  <div class="announcement" role="status" data-testid="announcement-banner">
    <span class="announcement-icon" aria-hidden="true">&#9888;</span>
    <p>
      {text}
      {#if url}
        <a href={url}>Read more</a>
      {/if}
    </p>
    <button class="announcement-close" onclick={dismiss} aria-label="Dismiss"
      >&times;</button
    >
  </div>
{/if}

<style>
  .announcement {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.65rem 2rem 0.65rem 1.5rem;
    background: rgba(200, 164, 78, 0.12);
    border-bottom: 1px solid rgba(200, 164, 78, 0.45);
  }

  .announcement-icon {
    color: var(--color-warning);
    font-size: 1.2rem;
    flex-shrink: 0;
  }

  .announcement p {
    margin: 0;
    flex: 1;
    color: var(--color-text);
    line-height: 1.5;
  }

  .announcement a {
    margin-left: 0.35rem;
    color: var(--color-gold);
    font-weight: 600;
    text-decoration: none;
    white-space: nowrap;
  }

  .announcement a:hover {
    color: var(--color-gold-hover);
  }

  .announcement-close {
    background: none;
    border: none;
    color: var(--color-text-secondary);
    font-size: 1.25rem;
    cursor: pointer;
    padding: 0;
    line-height: 1;
    flex-shrink: 0;
  }

  .announcement-close:hover {
    color: var(--color-text);
  }

  @media (max-width: 640px) {
    .announcement {
      padding: 0.6rem 1rem;
      font-size: var(--font-size-sm);
    }
  }
</style>
