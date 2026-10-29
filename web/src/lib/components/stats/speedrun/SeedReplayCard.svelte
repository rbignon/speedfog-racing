<script lang="ts">
  import { protectSeed, unprotectSeed, type SpeedrunSeed } from "$lib/api";
  import { seedPageHref } from "$lib/speedrun";

  let {
    seed,
    onprotect,
  }: {
    seed: SpeedrunSeed;
    /** After a protection changed, so the page can refresh what it shows. */
    onprotect?: () => void;
  } = $props();

  // The server's answer to a protection overrides the page's copy until the
  // page hands a new seed down.
  let viewer = $derived(seed.viewer);
  let busy = $state(false);
  let error = $state<string | null>(null);

  let atLimit = $derived(
    viewer !== null && viewer.protected_seeds.length >= viewer.protection_limit,
  );

  async function toggleProtection() {
    if (viewer === null) return;
    busy = true;
    error = null;
    try {
      viewer = viewer.protected
        ? await unprotectSeed(seed.seed_number)
        : await protectSeed(seed.seed_number);
      onprotect?.();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to update";
    } finally {
      busy = false;
    }
  }
</script>

<section class="replay-card">
  <h3>Play this seed in Set Seed</h3>
  <p>
    Replay it <strong>as many times as you like</strong>. Your runs count on the
    <strong class="board">{seed.category_name} · Set Seed</strong> board, ranked with
    every blind run on this seed.
  </p>
  <p>
    They never enter <strong>Random Seed</strong>, which stays for blind runs.
  </p>
  {#if !seed.replayable}
    <p class="not-replayable">{seed.not_replayable_reason}</p>
  {/if}

  {#if viewer}
    <div class="protect">
      <div class="protect-text">
        <strong>Protect this seed</strong>
        <span class="quota"
          >Keeps this seed's files from being purged. You protect {viewer
            .protected_seeds.length} of your {viewer.protection_limit} seeds.</span
        >
      </div>
      {#if viewer.protected}
        <button
          type="button"
          class="btn btn-outline btn-sm"
          disabled={busy}
          onclick={toggleProtection}>Unprotect</button
        >
      {:else if !seed.protectable}
        <span class="hint"
          >Protection only keeps the files of a replayable seed.</span
        >
      {:else if !viewer.can_protect}
        <span class="hint"
          >Only players who finished a run on this seed can protect it.</span
        >
      {:else}
        <button
          type="button"
          class="btn btn-outline btn-sm"
          disabled={busy || atLimit}
          onclick={toggleProtection}>Protect</button
        >
      {/if}
      {#if !viewer.protected && seed.protectable && viewer.can_protect && atLimit}
        <p class="hint mine">
          To protect this one, unprotect one of yours first:
          <span class="mine-list">
            {#each viewer.protected_seeds as number (number)}
              <a href={seedPageHref(number)}>{number}</a>
            {/each}
          </span>
        </p>
      {/if}
      {#if error}
        <p class="error">{error}</p>
      {/if}
    </div>
  {/if}
</section>

<style>
  /* The race page's rules card, given more room. */
  .replay-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-left: 3px solid var(--color-gold);
    border-radius: var(--radius-sm);
    padding: 1.4rem 1.6rem;
  }

  h3 {
    margin: 0 0 0.9rem;
    font-size: 1.5rem;
    letter-spacing: 0.02em;
    color: var(--color-text);
  }

  p {
    margin: 0 0 0.55rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-base);
    line-height: 1.65;
  }

  strong {
    color: var(--color-text);
  }

  strong.board {
    color: var(--color-gold);
  }

  .not-replayable {
    margin-top: 0.65rem;
    color: var(--color-text);
  }

  .protect {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.6rem 1rem;
    margin-top: 0.9rem;
    padding-top: 0.8rem;
    border-top: 1px solid var(--color-border);
  }

  .protect-text {
    flex: 1 1 18rem;
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    font-size: var(--font-size-sm);
  }

  .quota,
  .hint {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
  }

  .hint.mine {
    flex-basis: 100%;
    margin: 0;
    line-height: 1.5;
  }

  .mine-list {
    display: inline-flex;
    flex-wrap: wrap;
    gap: 0.2rem 0.75rem;
    margin-left: 0.25rem;
  }

  .hint.mine a {
    font-family: var(--font-mono);
    color: var(--color-purple);
    text-decoration: none;
  }

  .hint.mine a:hover {
    color: var(--color-purple-hover);
  }

  .btn-sm {
    padding: 0.3rem 0.8rem 0.35rem;
    font-size: var(--font-size-sm);
  }

  .error {
    flex-basis: 100%;
    margin: 0;
    color: var(--color-danger);
    font-size: var(--font-size-xs);
  }

  @media (max-width: 768px) {
    .replay-card {
      padding: 1rem 1.1rem;
    }

    h3 {
      font-size: 1.25rem;
    }
  }
</style>
