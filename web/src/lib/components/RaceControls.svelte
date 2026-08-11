<script lang="ts">
  import {
    releaseSeeds,
    rerollSeed,
    startRace,
    resetRace,
    finishRace,
    fetchRace,
    updateRace,
    type RaceDetail,
  } from "$lib/api";
  import { auth } from "$lib/stores/auth.svelte";
  import ConfirmModal from "./ConfirmModal.svelte";
  import DropdownMenu from "./DropdownMenu.svelte";

  interface Props {
    race: RaceDetail;
    raceStatus: string;
    onRaceUpdated: (race: RaceDetail) => void;
    onDeleteRace: () => void;
  }

  let { race, raceStatus, onRaceUpdated, onDeleteRace }: Props = $props();

  let loading = $state(false);
  let error = $state<string | null>(null);
  let seedsReleased = $derived(race.seeds_released_at !== null);
  let canStart = $derived(race.participants.length >= 2 || auth.isAdmin);
  let isDaily = $derived(race.daily_date !== null);
  let canReroll = $derived(
    raceStatus === "setup" || (isDaily && raceStatus === "running"),
  );

  let reportBuggy = $state(false);
  let reportReason = $state("");

  // Registration settings inline editing
  let editingRegistration = $state(false);
  let regOpen = $state(false);
  let regMax = $state<number | "">(2);
  let savingRegistration = $state(false);
  let registrationError = $state<string | null>(null);

  // Visibility toggle
  let togglingVisibility = $state(false);

  let pendingConfirm = $state<{
    title: string;
    message: string;
    confirmLabel: string;
    danger?: boolean;
    action: () => Promise<void>;
  } | null>(null);

  function requestConfirm(opts: NonNullable<typeof pendingConfirm>) {
    pendingConfirm = opts;
  }

  async function executeConfirm() {
    if (!pendingConfirm) return;
    const action = pendingConfirm.action;
    pendingConfirm = null;
    await action();
  }

  async function handleRelease() {
    loading = true;
    error = null;
    try {
      const updated = await releaseSeeds(race.id);
      onRaceUpdated(updated);
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to release seeds";
    } finally {
      loading = false;
    }
  }

  function handleReroll() {
    // Daily reroll discards every in-flight run, so the bug-report opt-in
    // is on by default; for setup races we keep the legacy "ask me" flow.
    reportBuggy = isDaily;
    reportReason = "";
    const message = isDaily
      ? "Rerolling will discard all current and finished runs for this Daily Seed. The new seed will be released immediately. Continue?"
      : seedsReleased
        ? "Participants may have already downloaded. Re-rolling will require everyone to re-download. Continue?"
        : "Re-roll the seed? Participants will need to download a new seed pack.";
    requestConfirm({
      title: "Re-roll Seed",
      message,
      confirmLabel: "Re-roll",
      async action() {
        loading = true;
        error = null;
        try {
          const updated = await rerollSeed(
            race.id,
            reportBuggy || undefined,
            reportReason.trim() || undefined,
          );
          onRaceUpdated(updated);
        } catch (e) {
          error = e instanceof Error ? e.message : "Failed to re-roll seed";
        } finally {
          loading = false;
        }
      },
    });
  }

  function handleStart() {
    requestConfirm({
      title: "Start Race",
      message: "Start the race? All participants will be notified.",
      confirmLabel: "Start",
      async action() {
        loading = true;
        error = null;
        try {
          await startRace(race.id);
          const updated = await fetchRace(race.id);
          onRaceUpdated(updated);
        } catch (e) {
          error = e instanceof Error ? e.message : "Failed to start race";
        } finally {
          loading = false;
        }
      },
    });
  }

  function handleReset() {
    requestConfirm({
      title: "Reset Race",
      message: "Reset this race? All participant progress will be cleared.",
      confirmLabel: "Reset",
      danger: true,
      async action() {
        loading = true;
        error = null;
        try {
          await resetRace(race.id);
          const updated = await fetchRace(race.id);
          onRaceUpdated(updated);
        } catch (e) {
          error = e instanceof Error ? e.message : "Failed to reset race";
        } finally {
          loading = false;
        }
      },
    });
  }

  function handleForceFinish() {
    requestConfirm({
      title: "Force Finish",
      message:
        "Force finish this race? Non-finished participants will keep their current progress.",
      confirmLabel: "Force Finish",
      async action() {
        loading = true;
        error = null;
        try {
          await finishRace(race.id);
          const updated = await fetchRace(race.id);
          onRaceUpdated(updated);
        } catch (e) {
          error = e instanceof Error ? e.message : "Failed to finish race";
        } finally {
          loading = false;
        }
      },
    });
  }

  function handleDeleteRace() {
    requestConfirm({
      title: "Delete Race",
      message:
        "Permanently delete this race? This cannot be undone. All participant data will be lost.",
      confirmLabel: "Delete",
      danger: true,
      async action() {
        onDeleteRace();
      },
    });
  }

  async function handleToggleVisibility() {
    togglingVisibility = true;
    try {
      await updateRace(race.id, { is_public: !race.is_public });
      onRaceUpdated(await fetchRace(race.id));
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to toggle visibility";
    } finally {
      togglingVisibility = false;
    }
  }

  function openRegistrationEdit() {
    regOpen = race.open_registration;
    regMax = race.max_participants ?? 2;
    registrationError = null;
    editingRegistration = true;
  }

  function cancelRegistrationEdit() {
    editingRegistration = false;
    registrationError = null;
  }

  async function saveRegistration() {
    savingRegistration = true;
    registrationError = null;
    try {
      let maxVal: number | null = null;
      if (regOpen) {
        const n = Number(regMax);
        if (!Number.isInteger(n) || n < 2 || n > 100) {
          registrationError = "Max participants must be between 2 and 100";
          savingRegistration = false;
          return;
        }
        maxVal = n;
      }
      await updateRace(race.id, {
        open_registration: regOpen,
        max_participants: maxVal,
      });
      const updated = await fetchRace(race.id);
      onRaceUpdated(updated);
      editingRegistration = false;
    } catch (e) {
      registrationError =
        e instanceof Error ? e.message : "Failed to save registration settings";
    } finally {
      savingRegistration = false;
    }
  }

  let registrationLabel = $derived.by(() => {
    if (!race.open_registration) return "Invite only";
    if (race.max_participants !== null)
      return `Open (${race.max_participants} max)`;
    return "Open";
  });

  let dropdownItems = $derived.by(() => {
    const items = [];
    if (raceStatus === "running" || raceStatus === "finished") {
      items.push({ label: "Reset Race", danger: true, onclick: handleReset });
    }
    items.push({
      label: "Delete Race",
      danger: true,
      onclick: handleDeleteRace,
    });
    return items;
  });
</script>

<div class="toolbar">
  <div class="toolbar-row">
    <div class="toolbar-actions">
      {#if raceStatus === "setup"}
        {#if seedsReleased}
          <button
            class="btn btn-primary"
            onclick={handleStart}
            disabled={loading || !canStart}
            title={!canStart ? "At least 2 participants required" : undefined}
          >
            {loading ? "Starting..." : "Start Race"}
          </button>
        {:else}
          <button
            class="btn btn-primary"
            onclick={handleRelease}
            disabled={loading}
          >
            {loading ? "Releasing..." : "Release Seeds"}
          </button>
        {/if}
        {#if seedsReleased}
          <span class="seeds-badge">
            <svg
              width="12"
              height="12"
              viewBox="0 0 24 24"
              fill="none"
              stroke="currentColor"
              stroke-width="3"
              stroke-linecap="round"
              stroke-linejoin="round"><polyline points="20 6 9 17 4 12" /></svg
            >
            Seeds ready
          </span>
        {/if}
        <button
          class="btn btn-secondary"
          onclick={handleReroll}
          disabled={loading}
        >
          {loading ? "Re-rolling..." : "Re-roll Seed"}
        </button>
      {:else if raceStatus === "running"}
        {#if canReroll}
          <button
            class="btn btn-outline"
            onclick={handleReroll}
            disabled={loading}
          >
            {loading ? "Re-rolling..." : "Re-roll Seed"}
          </button>
        {:else}
          <button
            class="btn btn-outline"
            onclick={handleForceFinish}
            disabled={loading}
          >
            {loading ? "Finishing..." : "Force Finish"}
          </button>
        {/if}
      {/if}

      {#if error}
        <span class="toolbar-error">{error}</span>
      {/if}
    </div>

    <div class="toolbar-settings">
      <button
        class="btn-icon-label"
        onclick={handleToggleVisibility}
        disabled={togglingVisibility}
        title={race.is_public
          ? "Public — click to make private"
          : "Private — click to make public"}
      >
        {#if race.is_public}
          <svg
            viewBox="0 0 20 20"
            fill="currentColor"
            width="14"
            height="14"
            aria-hidden="true"
          >
            <path d="M10 12a2 2 0 100-4 2 2 0 000 4z" />
            <path
              fill-rule="evenodd"
              d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z"
              clip-rule="evenodd"
            />
          </svg>
          <span>Public</span>
        {:else}
          <svg
            viewBox="0 0 20 20"
            fill="currentColor"
            width="14"
            height="14"
            aria-hidden="true"
          >
            <path
              fill-rule="evenodd"
              d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074l-1.78-1.781zm4.261 4.26l1.514 1.515a2.003 2.003 0 012.45 2.45l1.514 1.514a4 4 0 00-5.478-5.478z"
              clip-rule="evenodd"
            />
            <path
              d="M12.454 16.697L9.75 13.992a4 4 0 01-3.742-3.741L2.335 6.578A9.98 9.98 0 00.458 10c1.274 4.057 5.065 7 9.542 7 .847 0 1.669-.105 2.454-.303z"
            />
          </svg>
          <span>Private</span>
        {/if}
      </button>

      {#if raceStatus === "setup"}
        {#if editingRegistration}
          <div class="reg-edit">
            <label class="reg-check">
              <input type="checkbox" bind:checked={regOpen} />
              Open registration
            </label>
            {#if regOpen}
              <input
                class="reg-max-input"
                type="number"
                min="2"
                max="100"
                placeholder="2-100"
                bind:value={regMax}
              />
            {/if}
            {#if registrationError}
              <span class="toolbar-error">{registrationError}</span>
            {/if}
            <button
              class="btn btn-primary btn-sm"
              onclick={saveRegistration}
              disabled={savingRegistration}
            >
              {savingRegistration ? "Saving..." : "Save"}
            </button>
            <button
              class="btn btn-secondary btn-sm"
              onclick={cancelRegistrationEdit}
              disabled={savingRegistration}
            >
              Cancel
            </button>
          </div>
        {:else}
          <button
            class="btn-icon-label"
            onclick={openRegistrationEdit}
            title="Edit registration settings"
          >
            <svg
              viewBox="0 0 20 20"
              fill="currentColor"
              width="14"
              height="14"
              aria-hidden="true"
            >
              <path
                fill-rule="evenodd"
                d="M10 9a3 3 0 100-6 3 3 0 000 6zm-7 9a7 7 0 1114 0H3z"
                clip-rule="evenodd"
              />
            </svg>
            <span>{registrationLabel}</span>
          </button>
        {/if}
      {/if}

      <DropdownMenu items={dropdownItems} />
    </div>
  </div>
</div>

{#if pendingConfirm}
  <ConfirmModal
    title={pendingConfirm.title}
    message={pendingConfirm.message}
    confirmLabel={pendingConfirm.confirmLabel}
    danger={pendingConfirm.danger ?? false}
    onConfirm={executeConfirm}
    onCancel={() => (pendingConfirm = null)}
  >
    {#if pendingConfirm.title === "Re-roll Seed"}
      <label class="report-check">
        <input type="checkbox" bind:checked={reportBuggy} />
        Report this seed as buggy
      </label>
      {#if reportBuggy}
        <input
          class="report-reason"
          type="text"
          placeholder="Describe the issue..."
          bind:value={reportReason}
          maxlength="500"
        />
      {/if}
    {/if}
  </ConfirmModal>
{/if}

<style>
  .toolbar {
    border-top: 1px solid var(--color-border);
    padding-top: 0.75rem;
    margin-top: 0.75rem;
  }

  .toolbar-row {
    display: flex;
    align-items: flex-start;
    gap: 0.5rem;
    flex-wrap: wrap;
    justify-content: space-between;
  }

  .toolbar-actions {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .toolbar-settings {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-wrap: wrap;
  }

  .seeds-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
    color: var(--color-success, #10b981);
    background: rgba(16, 185, 129, 0.1);
    padding: 0.25rem 0.5rem;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-xs);
    font-weight: 600;
    white-space: nowrap;
  }

  .toolbar-error {
    color: var(--color-danger);
    font-size: var(--font-size-xs);
  }

  .btn-icon-label {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    background: none;
    border: 1px solid var(--color-border);
    color: var(--color-text-secondary);
    border-radius: var(--radius-sm);
    padding: 0.35rem 0.6rem;
    font-family: var(--font-family);
    font-size: var(--font-size-xs);
    cursor: pointer;
    transition: all var(--transition);
    white-space: nowrap;
  }

  .btn-icon-label:hover:not(:disabled) {
    border-color: var(--color-text-secondary);
    color: var(--color-text);
  }

  .btn-icon-label:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .reg-edit {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    flex-wrap: wrap;
  }

  .reg-check {
    display: flex;
    align-items: center;
    gap: 0.3rem;
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    cursor: pointer;
    white-space: nowrap;
  }

  .reg-check input[type="checkbox"] {
    accent-color: var(--color-gold);
    cursor: pointer;
  }

  .reg-max-input {
    width: 5rem;
    padding: 0.25rem 0.4rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-xs);
  }

  .reg-max-input:focus {
    outline: none;
    border-color: var(--color-gold);
  }

  .btn-sm {
    padding: 0.25rem 0.5rem;
    font-size: var(--font-size-xs);
  }

  .report-check {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    cursor: pointer;
    margin-bottom: 0.5rem;
  }

  .report-check input[type="checkbox"] {
    accent-color: var(--color-gold);
    cursor: pointer;
  }

  .report-reason {
    width: 100%;
    padding: 0.4rem 0.6rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    margin-bottom: 0.75rem;
    box-sizing: border-box;
  }

  .report-reason:focus {
    outline: none;
    border-color: var(--color-gold);
  }
</style>
