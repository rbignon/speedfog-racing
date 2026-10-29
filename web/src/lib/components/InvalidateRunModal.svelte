<script lang="ts">
  import { untrack } from "svelte";
  import { invalidateSession, type TrainingSessionDetail } from "$lib/api";
  import ConfirmModal from "./ConfirmModal.svelte";

  interface Props {
    sessionId: string;
    suggestedReason?: string;
    onDone: (session: TrainingSessionDetail) => void;
    onClose: () => void;
  }

  let { sessionId, suggestedReason = "", onDone, onClose }: Props = $props();

  let reason = $state(untrack(() => suggestedReason));
  let loading = $state(false);
  let error = $state<string | null>(null);

  async function confirm() {
    if (!reason.trim()) {
      error = "A reason is required.";
      return;
    }
    loading = true;
    error = null;
    try {
      onDone(await invalidateSession(sessionId, reason.trim()));
    } catch (e) {
      error = e instanceof Error ? e.message : "Invalidation failed.";
    } finally {
      loading = false;
    }
  }
</script>

<ConfirmModal
  title="Invalidate this run"
  message="The run leaves the boards, the seed page and the records, and shows the reason publicly. You can cancel it later."
  confirmLabel="Invalidate"
  danger
  {loading}
  {error}
  onConfirm={confirm}
  onCancel={onClose}
>
  <label class="field">
    <span>Reason</span>
    <textarea bind:value={reason} maxlength="500" rows="3"></textarea>
  </label>
</ConfirmModal>

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin-bottom: 0.75rem;
    font-size: var(--font-size-sm);
  }

  textarea {
    font: inherit;
  }
</style>
