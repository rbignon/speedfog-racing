<script lang="ts">
  import { untrack } from "svelte";
  import {
    cancelDisqualification,
    disqualifyParticipant,
    type Participant,
    type RaceDetail,
  } from "$lib/api";
  import ConfirmModal from "./ConfirmModal.svelte";

  interface Props {
    race: RaceDetail;
    preselectedId?: string | null;
    suggestedReason?: string;
    onDone: (race: RaceDetail) => void;
    onClose: () => void;
  }

  let {
    race,
    preselectedId = null,
    suggestedReason = "",
    onDone,
    onClose,
  }: Props = $props();

  let eligible = $derived(
    race.participants.filter((p) => p.status !== "disqualified"),
  );
  let disqualified = $derived(
    race.participants.filter((p) => p.status === "disqualified"),
  );
  let selectedId = $state(untrack(() => preselectedId ?? ""));
  let reason = $state(untrack(() => suggestedReason));
  let loading = $state(false);
  let error = $state<string | null>(null);

  function runnerName(p: Participant): string {
    return p.user.twitch_display_name || p.user.twitch_username;
  }

  async function confirm() {
    if (!selectedId) {
      error = "Pick a runner.";
      return;
    }
    if (!reason.trim()) {
      error = "A reason is required.";
      return;
    }
    loading = true;
    error = null;
    try {
      onDone(await disqualifyParticipant(race.id, selectedId, reason.trim()));
    } catch (e) {
      error = e instanceof Error ? e.message : "Disqualification failed.";
    } finally {
      loading = false;
    }
  }

  async function cancel(participantId: string) {
    loading = true;
    error = null;
    try {
      onDone(await cancelDisqualification(race.id, participantId));
    } catch (e) {
      error = e instanceof Error ? e.message : "Cancellation failed.";
    } finally {
      loading = false;
    }
  }
</script>

<ConfirmModal
  title="Disqualify a runner"
  message="The runner keeps a DQ tag and gets no result, points or rewards from this race. You can cancel it later."
  confirmLabel="Disqualify"
  danger
  {loading}
  {error}
  onConfirm={confirm}
  onCancel={onClose}
>
  <label class="field">
    <span>Runner</span>
    <select bind:value={selectedId}>
      <option value="" disabled>Choose a runner</option>
      {#each eligible as p (p.id)}
        <option value={p.id}>{runnerName(p)}</option>
      {/each}
    </select>
  </label>
  <label class="field">
    <span>Reason</span>
    <textarea bind:value={reason} maxlength="500" rows="3"></textarea>
  </label>
  {#if disqualified.length > 0}
    <h3>Disqualified</h3>
    <ul class="dq-list">
      {#each disqualified as p (p.id)}
        <li>
          <span class="runner">{runnerName(p)}</span>
          {#if p.disqualification_reason}
            <span class="reason">{p.disqualification_reason}</span>
          {/if}
          <button
            type="button"
            class="btn btn-outline"
            disabled={loading}
            onclick={() => cancel(p.id)}>Cancel disqualification</button
          >
        </li>
      {/each}
    </ul>
  {/if}
</ConfirmModal>

<style>
  .field {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
    margin-bottom: 0.75rem;
    font-size: var(--font-size-sm);
  }

  select,
  textarea {
    font: inherit;
  }

  h3 {
    margin: 1rem 0 0.5rem;
    font-size: var(--font-size-sm);
    text-transform: uppercase;
    letter-spacing: 0.06em;
    color: var(--color-text-secondary);
  }

  .dq-list {
    list-style: none;
    margin: 0;
    padding: 0;
  }

  .dq-list li {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
    padding: 0.35rem 0;
  }

  .runner {
    font-weight: 600;
  }

  .reason {
    color: var(--color-text-secondary);
    flex: 1;
  }
</style>
