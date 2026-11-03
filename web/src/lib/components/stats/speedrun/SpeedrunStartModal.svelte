<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { goto } from "$app/navigation";
  import {
    fetchFreshSpeedrunSeeds,
    fetchSpeedrunSeedSummary,
    getTwitchLoginUrl,
    startSpeedrunSolo,
    type SpeedrunSeedSummary,
  } from "$lib/api";
  import { formatIgt } from "$lib/dag/popupData";
  import {
    SEED_ID_MIN_LENGTH,
    setSeedRaceNewHref,
    speedrunRaceNewHref,
  } from "$lib/speedrun";
  import { auth } from "$lib/stores/auth.svelte";
  import SpeedrunRules from "./SpeedrunRules.svelte";

  interface Props {
    /** The board's category key: Random Seed draws from it. */
    pool: string;
    categoryName: string;
    /** A retired category: no Random Seed run on it. */
    retired?: boolean;
    /** Opens in Set Seed mode with this seed ID typed in. */
    initialSeed?: string | null;
    /** The seed of the record on the board shown: the WR button types it. */
    recordSeed?: string | null;
    onClose: () => void;
  }

  let {
    pool,
    categoryName,
    retired = false,
    initialSeed = null,
    recordSeed = null,
    onClose,
  }: Props = $props();

  type SeedMode = "random" | "set";
  type Format = "solo" | "race";

  let seedMode = $state<SeedMode>(
    untrack(() => (initialSeed === null ? "random" : "set")),
  );
  let format = $state<Format>("solo");
  let seedInput = $state(untrack(() => initialSeed ?? ""));
  // Null until the server answers.
  let fresh = $state<boolean | null>(null);
  // A retired category (an archive, `<pool>@<layers>`, always is) or a pool
  // the server cannot draw from: Random Seed runs are closed.
  let closed = $state(untrack(() => retired || pool.includes("@")));
  let summary = $state<SpeedrunSeedSummary | null>(null);
  let lookupError = $state<string | null>(null);
  let checking = $state(false);
  let starting = $state(false);
  let error = $state<string | null>(null);

  // Only organizers and admins create races; everyone else plays solo.
  let canRace = $derived(auth.canCreateRace);
  let chosenFormat = $derived<Format>(canRace ? format : "solo");
  let typed = $derived(seedInput.trim());
  // Set Seed plays the seed's category, Random Seed draws from the board's.
  let shownCategory = $derived(
    seedMode === "set" && summary ? summary.category_name : categoryName,
  );
  let setBoard = $derived(
    summary ? `${summary.category_name} · Set Seed` : "Set Seed",
  );
  // " · WR <time> by <player>" for a seed with a run, nothing otherwise.
  let recordText = $derived.by(() => {
    const record = summary?.record;
    if (!record) return "";
    const name = record.user.twitch_display_name ?? record.user.twitch_username;
    return ` · WR ${formatIgt(record.igt_ms)} by ${name}`;
  });
  let ready = $derived(
    seedMode === "random"
      ? !closed && fresh === true
      : summary !== null && summary.replayable,
  );

  onMount(() => {
    if (closed) return;
    // A pool that cannot host a Speedrun run (disabled) answers 404.
    fetchFreshSpeedrunSeeds(pool)
      .then((r) => {
        if (r === null) closed = true;
        else fresh = r.fresh;
      })
      .catch(() => (fresh = false));
  });

  // A refusal belongs to the choice it answered: a new choice clears it.
  function chooseSeedMode(mode: SeedMode) {
    seedMode = mode;
    error = null;
  }

  function chooseFormat(next: Format) {
    format = next;
    error = null;
  }

  // The Seed ID is checked as typed, once typing pauses; a response that
  // lands after a newer keystroke is dropped.
  let lookupId = 0;
  $effect(() => {
    const text = typed;
    const id = ++lookupId;
    summary = null;
    lookupError = null;
    error = null;
    if (text.length < SEED_ID_MIN_LENGTH) {
      checking = false;
      return;
    }
    checking = true;
    const timer = setTimeout(() => {
      fetchSpeedrunSeedSummary(text)
        .then((s) => {
          if (id === lookupId) summary = s;
        })
        .catch((e) => {
          if (id === lookupId)
            lookupError = e instanceof Error ? e.message : "Unknown seed";
        })
        .finally(() => {
          if (id === lookupId) checking = false;
        });
    }, 300);
    return () => clearTimeout(timer);
  });

  async function start() {
    if (!ready || starting) return;
    const seed = seedMode === "set" ? (summary?.seed_number ?? null) : null;
    if (chosenFormat === "race") {
      goto(
        seed === null ? speedrunRaceNewHref(pool) : setSeedRaceNewHref(seed),
      );
      return;
    }
    starting = true;
    error = null;
    try {
      const session = await startSpeedrunSolo(
        seed === null ? { pool } : { seed },
      );
      goto(`/training/${session.id}`);
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to start the run.";
      starting = false;
    }
  }

  // Back to this board after the Twitch round trip.
  function rememberPage() {
    sessionStorage.setItem(
      "redirect_after_login",
      window.location.pathname + window.location.search,
    );
  }
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div
  class="modal-backdrop"
  onclick={onClose}
  onkeydown={(e) => e.key === "Escape" && onClose()}
>
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="modal" onclick={(e) => e.stopPropagation()}>
    <div class="modal-header">
      <h2>Start a run</h2>
      <button class="close-btn" aria-label="Close" onclick={onClose}
        >&times;</button
      >
    </div>

    <p class="description">
      A ranked run for this board. To play without a ranking, use
      <a href="/training">Solo</a>.
    </p>

    <div class="config-row">
      <span class="row-label">Category</span>
      <span class="chip category-chip">{shownCategory}</span>
    </div>

    <!-- The board's subcategories, in its order. -->
    <div class="config-row">
      <span class="row-label">Subcategory</span>
      <div class="segmented">
        <button
          type="button"
          class:on={seedMode === "set"}
          aria-pressed={seedMode === "set"}
          onclick={() => chooseSeedMode("set")}>Set Seed</button
        >
        <button
          type="button"
          class:on={seedMode === "random"}
          aria-pressed={seedMode === "random"}
          onclick={() => chooseSeedMode("random")}>Random Seed</button
        >
      </div>
    </div>

    {#if seedMode === "set"}
      <div class="config-row">
        <label for="start-run-seed" class="row-label">Seed ID</label>
        <input
          id="start-run-seed"
          type="text"
          class="config-input seed-input"
          bind:value={seedInput}
          autocomplete="off"
          spellcheck="false"
          maxlength="32"
        />
        {#if recordSeed}
          <button
            type="button"
            class="btn btn-outline btn-sm wr-btn"
            title="Type in the seed of the record on the board"
            onclick={() => (seedInput = recordSeed ?? "")}>WR</button
          >
        {/if}
      </div>
      {#if lookupError}
        <p class="config-hint seed-check bad">{lookupError}</p>
      {:else if summary?.replayable}
        <p class="config-hint seed-check ok">
          &#10003; Replayable{recordText}
        </p>
      {:else if summary}
        <p class="config-hint seed-check bad">
          {summary.not_replayable_reason}
        </p>
      {:else if checking}
        <p class="config-hint seed-check">Checking...</p>
      {:else if typed.length < SEED_ID_MIN_LENGTH}
        <p class="config-hint seed-check">
          The full seed ID, or the 6 characters shown on the boards.
        </p>
      {/if}
    {/if}

    {#if canRace}
      <div class="config-row">
        <span class="row-label">Format</span>
        <div class="segmented">
          <button
            type="button"
            class:on={format === "solo"}
            aria-pressed={format === "solo"}
            onclick={() => chooseFormat("solo")}>Solo</button
          >
          <button
            type="button"
            class:on={format === "race"}
            aria-pressed={format === "race"}
            onclick={() => chooseFormat("race")}>Race</button
          >
        </div>
      </div>
    {/if}

    <p class="config-hint explain">
      {#if seedMode === "random" && chosenFormat === "solo"}
        You get <strong>a seed nobody has played</strong>. Map, spoiler and
        ghosts stay hidden until you finish. Ranked on
        <strong class="board">{categoryName} · Random Seed</strong>, and on Set
        Seed too.
      {:else if seedMode === "random"}
        Runners get <strong>a seed nobody has played</strong>, drawn when the
        race is created. Ranked on
        <strong class="board">{categoryName} · Random Seed</strong>, and on Set
        Seed too.
      {:else if chosenFormat === "solo"}
        The seed sets the category. Spoiler available. Ranked on
        <strong class="board">{setBoard}</strong>.
      {:else}
        The seed sets the category, and <strong
          >runners may already know it</strong
        >. Ranked on <strong class="board">{setBoard}</strong> only.
      {/if}
    </p>

    {#if seedMode === "random" && closed}
      <p class="config-hint no-fresh">
        Random Seed runs are closed for this category.
      </p>
    {:else if seedMode === "random" && fresh === false}
      <p class="config-hint no-fresh">No fresh seed right now</p>
    {/if}

    <div class="rules">
      <SpeedrunRules />
    </div>

    {#if error}
      <p class="error" role="alert">{error}</p>
    {/if}

    <div class="actions">
      <button type="button" class="btn btn-secondary" onclick={onClose}
        >Cancel</button
      >
      {#if auth.isLoggedIn}
        <button
          type="button"
          class="btn btn-primary"
          disabled={!ready || starting}
          onclick={start}
        >
          {#if chosenFormat === "race"}
            Create race
          {:else}
            {starting ? "Starting..." : "Start solo"}
          {/if}
        </button>
      {:else}
        <a
          class="btn btn-twitch"
          href={getTwitchLoginUrl()}
          data-sveltekit-reload
          onclick={rememberPage}>Login with Twitch</a
        >
      {/if}
    </div>
  </div>
</div>

<style>
  /* The OBS overlay window's look (SpeedrunOverlayModal.svelte). */
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
    max-width: 500px;
    width: 90%;
    max-height: calc(100dvh - 2rem);
    overflow-y: auto;
    overscroll-behavior: contain;
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

  .description {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    margin: 0 0 1rem 0;
  }

  .description a {
    color: var(--color-purple);
  }

  .description a:hover {
    color: var(--color-purple-hover);
  }

  .config-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .row-label {
    min-width: 5rem;
  }

  .segmented {
    display: inline-flex;
    gap: 2px;
    padding: 2px;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }

  .segmented button {
    padding: 0.3rem 0.65rem;
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 600;
    cursor: pointer;
  }

  .segmented button:hover {
    color: var(--color-purple);
  }

  .segmented button.on {
    background: var(--color-gold);
    color: var(--color-ink-on-accent);
  }

  .category-chip {
    color: var(--color-gold);
    border-color: var(--color-gold);
  }

  .config-input {
    padding: 0.25rem 0.5rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
  }

  .config-input:focus {
    outline: none;
    border-color: var(--color-purple);
  }

  .seed-input {
    flex: 1;
    min-width: 0;
    max-width: 14rem;
  }

  /* The Seed ID field's height. */
  .wr-btn {
    padding: 0.25rem 0.6rem;
    font-size: var(--font-size-sm);
    line-height: normal;
    color: var(--color-gold);
    border-color: color-mix(in srgb, var(--color-gold) 60%, transparent);
  }

  .config-hint {
    margin: -0.25rem 0 0.75rem 0;
    font-size: var(--font-size-xs, 0.75rem);
    color: var(--color-text-disabled);
    line-height: 1.5;
  }

  .config-hint strong {
    color: var(--color-text);
  }

  .config-hint strong.board {
    color: var(--color-gold);
  }

  .seed-check.ok {
    color: var(--color-success);
  }

  .seed-check.bad,
  .no-fresh {
    color: var(--color-danger);
  }

  .explain {
    color: var(--color-text-secondary);
  }

  .rules {
    margin-top: 0.25rem;
    padding-top: 0.75rem;
    border-top: 1px solid var(--color-border);
    font-size: var(--font-size-xs, 0.75rem);
    color: var(--color-text-secondary);
  }

  .error {
    margin: 0.75rem 0 0;
    color: var(--color-danger);
    font-size: var(--font-size-sm);
  }

  .actions {
    display: flex;
    justify-content: flex-end;
    gap: 0.6rem;
    margin-top: 1.1rem;
  }

  /* Keeps the Subcategory label and its two buttons on one line down to
     360px phones. */
  @media (max-width: 400px) {
    .modal {
      padding: 1.5rem 1rem;
    }
  }
</style>
