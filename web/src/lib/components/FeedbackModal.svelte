<script lang="ts">
  import StarRating from "./StarRating.svelte";
  import { auth } from "$lib/stores/auth.svelte";
  import {
    submitFeedback,
    markFeedbackPrompted,
    type FeedbackSource,
  } from "$lib/api";

  interface Props {
    source: FeedbackSource;
    raceId?: string | null;
    entityKind?: "race" | "daily";
    onClose: () => void;
  }

  let { source, raceId = null, entityKind = "race", onClose }: Props = $props();

  let rating: number | null = $state(null);
  let comment = $state("");
  let submitting = $state(false);
  let done = $state(false);
  let error: string | null = $state(null);
  let closeTimer: ReturnType<typeof setTimeout> | null = null;

  const subtitle = $derived(
    source === "post_first_race" ? `How was your ${entityKind}?` : null,
  );

  $effect(() => {
    if (source === "post_first_race") {
      markFeedbackPrompted()
        .then(() => auth.markFeedbackPrompted())
        .catch(() => {
          // Silent: if the mark-prompted call fails (network blip), the
          // next mount will retry. We still show the modal.
        });
    }
  });

  $effect(() => {
    return () => {
      if (closeTimer !== null) {
        clearTimeout(closeTimer);
        closeTimer = null;
      }
    };
  });

  async function submit() {
    if (rating === null || submitting) return;
    submitting = true;
    error = null;
    try {
      await submitFeedback({
        rating,
        comment: comment.trim() || null,
        source,
        race_id: source === "post_first_race" ? raceId : null,
      });
      done = true;
      closeTimer = setTimeout(onClose, 1500);
    } catch (e) {
      error = e instanceof Error ? e.message : "Error";
    } finally {
      submitting = false;
    }
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="modal-backdrop"
  onclick={onClose}
  onkeydown={(e) => e.key === "Escape" && onClose()}
>
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div
    class="modal"
    role="dialog"
    aria-modal="true"
    tabindex="-1"
    onclick={(e) => e.stopPropagation()}
  >
    {#if done}
      <p class="thanks">Thanks for your feedback!</p>
    {:else}
      <div class="modal-header">
        <h2>Feedback</h2>
        <button class="close-btn" onclick={onClose} aria-label="Close"
          >&times;</button
        >
      </div>

      {#if subtitle}
        <p class="subtitle">{subtitle}</p>
      {/if}

      <div class="rating-row">
        <StarRating value={rating} onChange={(v) => (rating = v)} />
      </div>

      <textarea
        bind:value={comment}
        maxlength="1000"
        placeholder="What you liked, disliked, a suggestion... (optional)"
      ></textarea>

      {#if error}
        <p class="error">{error}</p>
      {/if}

      <div class="actions">
        <button
          class="btn btn-secondary"
          onclick={onClose}
          disabled={submitting}
        >
          Close
        </button>
        <button
          class="btn btn-primary"
          onclick={submit}
          disabled={rating === null || submitting}
        >
          {submitting ? "Sending..." : "Send"}
        </button>
      </div>
    {/if}
  </div>
</div>

<style>
  .modal-backdrop {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    display: flex;
    align-items: center;
    justify-content: center;
    z-index: 1000;
  }

  .modal {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
    max-width: 420px;
    width: 90%;
  }

  .modal-header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 0.75rem;
  }

  .modal-header h2 {
    margin: 0;
    color: var(--color-gold);
    font-size: var(--font-size-lg);
    font-weight: 600;
    letter-spacing: 0.06em;
    text-transform: uppercase;
  }

  .close-btn {
    background: none;
    border: none;
    color: var(--color-text-secondary);
    font-size: 1.5rem;
    cursor: pointer;
    padding: 0;
    line-height: 1;
  }

  .close-btn:hover {
    color: var(--color-text);
  }

  .subtitle {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    margin: 0 0 1rem 0;
    line-height: 1.5;
  }

  .rating-row {
    display: flex;
    justify-content: center;
    margin-bottom: 1rem;
  }

  textarea {
    width: 100%;
    min-height: 80px;
    background: var(--color-bg);
    color: var(--color-text);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 0.5rem 0.75rem;
    font-family: inherit;
    font-size: var(--font-size-sm);
    resize: vertical;
    box-sizing: border-box;
    margin-bottom: 0.75rem;
  }

  textarea:focus {
    outline: none;
    border-color: var(--color-gold);
  }

  .error {
    color: var(--color-danger);
    font-size: var(--font-size-sm);
    margin: 0 0 0.75rem 0;
  }

  .thanks {
    color: var(--color-gold);
    font-size: var(--font-size-lg);
    text-align: center;
    margin: 1rem 0;
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.5rem;
  }
</style>
