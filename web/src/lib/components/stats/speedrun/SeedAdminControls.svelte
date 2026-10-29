<script lang="ts">
  import {
    excludeSeedFromSetSeed,
    restoreSeedToSetSeed,
    type SpeedrunSeed,
  } from "$lib/api";

  let {
    seed,
    onchange,
  }: {
    seed: Pick<SpeedrunSeed, "seed_number" | "excluded_reason">;
    /** After an exclusion or a restore, so the page reloads the seed. */
    onchange: () => void | Promise<void>;
  } = $props();

  let reason = $state("");
  let busy = $state(false);
  let error = $state<string | null>(null);

  async function run(action: () => Promise<void>) {
    busy = true;
    error = null;
    try {
      await action();
      reason = "";
      await onchange();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to update";
    } finally {
      busy = false;
    }
  }
</script>

<section class="seed-admin" aria-label="Admin">
  <h3>Admin</h3>
  {#if seed.excluded_reason !== null}
    <div class="row">
      <span class="excluded"
        >Excluded from Set Seed: {seed.excluded_reason}</span
      >
      <button
        type="button"
        class="btn btn-outline btn-sm"
        disabled={busy}
        onclick={() => run(() => restoreSeedToSetSeed(seed.seed_number))}
        >Restore</button
      >
    </div>
  {:else}
    <div class="row">
      <input
        type="text"
        class="reason"
        aria-label="Exclusion reason"
        placeholder="Why this seed is broken"
        maxlength="500"
        bind:value={reason}
        disabled={busy}
      />
      <button
        type="button"
        class="btn btn-danger btn-sm"
        disabled={busy || reason.trim() === ""}
        onclick={() =>
          run(() => excludeSeedFromSetSeed(seed.seed_number, reason.trim()))}
        >Exclude from Set Seed</button
      >
    </div>
  {/if}
  {#if error}
    <p class="error">{error}</p>
  {/if}
</section>

<style>
  .seed-admin {
    border-top: 1px solid var(--color-border);
    padding-top: 0.75rem;
  }

  h3 {
    margin: 0 0 0.5rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 0.75rem;
  }

  .reason {
    flex: 1 1 16rem;
    min-width: 0;
  }

  .excluded {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .btn-sm {
    padding: 0.3rem 0.8rem 0.35rem;
    font-size: var(--font-size-sm);
  }

  .error {
    margin: 0.5rem 0 0;
    color: var(--color-danger);
    font-size: var(--font-size-xs);
  }
</style>
