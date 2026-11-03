<script lang="ts">
  import { untrack } from "svelte";
  import {
    fetchSpeedrunBoard,
    type SpeedrunBoardResponse,
    type SpeedrunCategory,
    type SpeedrunRunType,
  } from "$lib/api";
  import {
    RUN_TYPES,
    resolvePool,
    speedrunSeedHref,
    toggleRunType,
    type SpeedrunParams,
    type SpeedrunSub,
  } from "$lib/speedrun";
  import { downloadCategorySplits } from "$lib/livesplit-download";
  import SpeedrunHistory from "./SpeedrunHistory.svelte";
  import SpeedrunOverlayModal from "./SpeedrunOverlayModal.svelte";
  import SpeedrunPlayer from "./SpeedrunPlayer.svelte";
  import SpeedrunRules from "./SpeedrunRules.svelte";
  import SpeedrunStartModal from "./SpeedrunStartModal.svelte";
  import SpeedrunTable from "./SpeedrunTable.svelte";
  import SpeedrunTime from "./SpeedrunTime.svelte";

  let {
    categories,
    params,
    onchange,
    startSeed = null,
  }: {
    categories: SpeedrunCategory[];
    params: SpeedrunParams;
    onchange: (p: SpeedrunParams) => void;
    /** Opens the Start a run window in Set Seed mode on this seed ID. */
    startSeed?: string | null;
  } = $props();

  const TYPE_LABELS: Record<SpeedrunRunType, string> = {
    race: "Races",
    daily: "Daily Seeds",
    event: "Event races",
    solo: "Solo runs",
  };

  const SUBS: { sub: SpeedrunSub; label: string }[] = [
    { sub: "set", label: "Set Seed" },
    { sub: "random", label: "Random Seed" },
  ];

  let board = $state<SpeedrunBoardResponse | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let filtersOpen = $state(false);
  async function downloadSplits() {
    if (!pool) return;
    splitsError = null;
    try {
      await downloadCategorySplits(pool, null);
    } catch (e) {
      splitsError =
        e instanceof Error ? e.message : "Failed to build the splits.";
    }
  }

  let rulesOpen = $state(false);
  let moreOpen = $state(false);
  let overlayOpen = $state(false);
  let splitsError = $state<string | null>(null);
  // The seed the URL opened the window on, forgotten once it closes: the
  // toolbar button opens it fresh.
  let startOpen = $state(untrack(() => startSeed !== null));
  let startWith = $state(untrack(() => startSeed));
  let filtersEl = $state<HTMLElement | null>(null);

  let pool = $derived(resolvePool(params, categories));
  let category = $derived(categories.find((c) => c.pool === pool) ?? null);
  let active = $derived(categories.filter((c) => !c.retired));
  let retired = $derived(categories.filter((c) => c.retired));
  let showRetired = $derived(moreOpen || (category?.retired ?? false));
  // The record's holder: the first ranked row of the board.
  let recordRun = $derived(board?.runs.find((r) => r.rank !== null) ?? null);
  let ruleLines = $derived(
    (category?.rules ?? "")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0),
  );

  // A string, so the fetch below reruns only when the board itself changes
  // (not when the Leaderboard / History view toggles).
  let queryKey = $derived(
    pool
      ? [
          pool,
          params.sub,
          params.deathless,
          params.types.join(","),
          params.obsolete,
        ].join("|")
      : "",
  );

  // Plain counter: a response that lands after a newer request is dropped.
  let requestId = 0;

  $effect(() => {
    if (!queryKey) return;
    const target = untrack(() => pool);
    const { sub, deathless, types, obsolete } = untrack(() => params);
    if (!target) return;
    const id = ++requestId;
    loading = true;
    error = null;
    fetchSpeedrunBoard(target, {
      sub,
      deathless,
      types,
      obsolete,
    })
      .then((data) => {
        if (id === requestId) board = data;
      })
      .catch((e) => {
        if (id === requestId)
          error = e instanceof Error ? e.message : "Failed to load runs.";
      })
      .finally(() => {
        if (id === requestId) loading = false;
      });
  });

  function change(patch: Partial<SpeedrunParams>) {
    onchange({ ...params, ...patch });
  }

  function selectPool(next: string) {
    change({ pool: next });
  }

  function selectSub(sub: SpeedrunSub) {
    change({ pool, sub });
  }

  function handleWindowClick(e: MouseEvent) {
    if (filtersOpen && filtersEl && !filtersEl.contains(e.target as Node)) {
      filtersOpen = false;
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") filtersOpen = false;
  }
</script>

<svelte:window onclick={handleWindowClick} onkeydown={handleKeydown} />

<div class="sr-panel board">
  <div class="categories">
    {#each active as c (c.pool)}
      <button
        type="button"
        class="pill"
        class:on={c.pool === pool}
        onclick={() => selectPool(c.pool)}>{c.name}</button
      >
    {/each}
    {#if showRetired}
      {#each retired as c (c.pool)}
        <button
          type="button"
          class="pill"
          class:on={c.pool === pool}
          onclick={() => selectPool(c.pool)}>{c.name}</button
        >
      {/each}
    {/if}
    {#if retired.length > 0}
      <button
        type="button"
        class="more"
        class:open={showRetired}
        aria-expanded={showRetired}
        aria-label={showRetired ? "Hide more categories" : "More categories"}
        title={showRetired ? "Hide more categories" : "More categories"}
        onclick={() => (moreOpen = !showRetired)}
      >
        <svg viewBox="0 0 24 24" width="12" height="12" aria-hidden="true">
          <path
            d="m6 9 6 6 6-6"
            fill="none"
            stroke="currentColor"
            stroke-width="2.5"
          />
        </svg>
      </button>
    {/if}
  </div>

  {#if category}
    <div class="subcategories">
      <div class="label">{category.name} - Subcategories</div>
      <div class="segmented">
        {#each SUBS as { sub, label } (sub)}
          <button
            type="button"
            class:on={params.sub === sub}
            onclick={() => selectSub(sub)}>{label}</button
          >
        {/each}
      </div>
    </div>
  {/if}

  <!-- The record of the board on screen only: while the next one loads (its
       category or filters may differ) the band keeps its place, hidden and
       inert, so the toolbar and its open popover stay put; none beside a
       load error. -->
  {#if board?.record_seed && recordRun && !error}
    {@const seedHref = speedrunSeedHref(recordRun)}
    <div
      class="wr-seed"
      class:pending={loading}
      aria-hidden={loading ? "true" : undefined}
      inert={loading}
      data-testid="wr-seed"
    >
      <span class="chip wr-chip">WR seed</span>
      <a
        class="seed"
        class:gone={!board.record_seed.replayable}
        href={seedHref}
        title={board.record_seed.replayable
          ? undefined
          : "No longer replayable"}>{board.record_seed.seed_number}</a
      >
      <span class="wr-time"><SpeedrunTime ms={recordRun.igt_ms} /></span>
      <SpeedrunPlayer user={recordRun.user} />
      <span
        class="chip run-chip"
        class:blind={recordRun.blind}
        class:replay={!recordRun.blind}
        >{recordRun.blind ? "Blind" : "Replay"}</span
      >
      <span class="wr-runs"
        >{board.record_seed.runs} run{board.record_seed.runs === 1
          ? ""
          : "s"}</span
      >
      <span class="spacer"></span>
      <a class="tool" href={seedHref}>Open seed</a>
    </div>
  {/if}

  <div class="toolbar">
    <div class="segmented">
      <button
        type="button"
        class:on={params.view === "board"}
        onclick={() => change({ view: "board" })}
      >
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
          <path
            d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          />
        </svg>
        Leaderboard
      </button>
      <button
        type="button"
        class:on={params.view !== "board"}
        onclick={() =>
          params.view === "board" && change({ view: "history-chart" })}
      >
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
          <circle
            cx="12"
            cy="12"
            r="9"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          />
          <path
            d="M12 7v5l3 2"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          />
        </svg>
        History
      </button>
    </div>

    <div class="filters" bind:this={filtersEl}>
      <button
        type="button"
        class="tool"
        aria-expanded={filtersOpen}
        onclick={() => (filtersOpen = !filtersOpen)}
      >
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
          <path
            d="M4 6h10M18 6h2M4 12h4M12 12h8M4 18h12M14 4v4M8 10v4M16 16v4"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          />
        </svg>
        Filters
      </button>
      {#if filtersOpen}
        <div class="popover">
          {#each RUN_TYPES as t (t)}
            {@const checked = params.types.includes(t)}
            <label>
              <input
                type="checkbox"
                {checked}
                disabled={checked && params.types.length === 1}
                onchange={() =>
                  change({ types: toggleRunType(params.types, t) })}
              />
              {TYPE_LABELS[t]}
            </label>
          {/each}
          <hr />
          <label>
            <input
              type="checkbox"
              checked={params.deathless}
              onchange={() => change({ deathless: !params.deathless })}
            />
            Deathless only
          </label>
          <label>
            <input
              type="checkbox"
              checked={params.obsolete}
              onchange={() => change({ obsolete: !params.obsolete })}
            />
            Show obsolete runs
          </label>
        </div>
      {/if}
    </div>

    <span class="spacer"></span>

    {#if pool && category}
      <button type="button" class="tool" onclick={() => (overlayOpen = true)}>
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
          <path
            d="M3 4h18v12H3V4Zm5 16h8M12 16v4"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
          />
        </svg>
        OBS overlay
      </button>
    {/if}
    <button
      type="button"
      class="tool"
      aria-expanded={rulesOpen}
      onclick={() => (rulesOpen = !rulesOpen)}
    >
      <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
        <path
          d="M3 5c3-1 6-1 9 1 3-2 6-2 9-1v14c-3-1-6-1-9 1-3-2-6-2-9-1V5Zm9 1v14"
          fill="none"
          stroke="currentColor"
          stroke-width="2"
        />
      </svg>
      Rules
    </button>
    {#if pool && category}
      <button type="button" class="tool" onclick={downloadSplits}>
        LiveSplit
      </button>
      <button
        type="button"
        class="tool submit"
        onclick={() => (startOpen = true)}
      >
        <svg viewBox="0 0 24 24" width="13" height="13" aria-hidden="true">
          <circle cx="12" cy="12" r="10" fill="currentColor" />
          <path
            d="M12 7v10M7 12h10"
            stroke="var(--color-gold)"
            stroke-width="2.4"
          />
        </svg>
        Start a run
      </button>
    {/if}
  </div>

  {#if splitsError}
    <p class="message error" role="alert">{splitsError}</p>
  {/if}

  {#if rulesOpen && category}
    <div class="rules">
      <h4>Set Seed and Random Seed</h4>
      <p>
        <strong>Set Seed</strong>: every run, blind or replayed, except on a
        seed an admin excluded. Replay any seed as often as you like while its
        files are kept on the server; a struck-through seed can no longer be
        played.
      </p>
      <p>
        <strong>Random Seed</strong>: blind runs only, on a seed nobody had
        played.
      </p>
      <h4>Speedrun rules</h4>
      <SpeedrunRules title={null} />
      <h4>{category.name} rules</h4>
      {#if category.description}
        <p>{category.description}</p>
      {/if}
      {#if category.estimated_duration}
        <p class="muted">Estimated duration: {category.estimated_duration}</p>
      {/if}
      {#if ruleLines.length > 0}
        <h5>Mode rules</h5>
        <ul>
          {#each ruleLines as line, i (i)}
            <li>{line}</li>
          {/each}
        </ul>
      {/if}
    </div>
  {/if}

  <div class="content" class:stale={loading && board !== null}>
    {#if error}
      <p class="message error">{error}</p>
    {:else if board === null}
      <p class="message">Loading runs...</p>
    {:else if params.view !== "board" && category}
      <SpeedrunHistory
        records={board.history}
        {category}
        view={params.view}
        onview={(view) => change({ view })}
      />
    {:else if board.runs.length === 0}
      <p class="message">No runs match these filters.</p>
    {:else}
      {#key queryKey}
        <SpeedrunTable runs={board.runs} showRun={params.sub === "set"} />
      {/key}
    {/if}
  </div>
</div>

{#if overlayOpen && pool && category}
  <SpeedrunOverlayModal
    {pool}
    categoryName={category.name}
    sub={params.sub}
    deathless={params.deathless}
    types={params.types}
    onClose={() => (overlayOpen = false)}
  />
{/if}

{#if startOpen && pool && category}
  <SpeedrunStartModal
    {pool}
    categoryName={category.name}
    retired={category.retired}
    initialSeed={startWith}
    recordSeed={loading || error || !board?.record_seed?.replayable
      ? null
      : board.record_seed.seed_number}
    onClose={() => {
      startOpen = false;
      startWith = null;
    }}
  />
{/if}

<style>
  .board {
    min-width: 0;
  }

  .categories {
    position: relative;
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.35rem;
    padding: 0.55rem 2.6rem 0.55rem 0.55rem;
    border-bottom: 1px solid var(--color-border);
  }

  .pill {
    padding: 0.38rem 0.65rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 700;
    white-space: nowrap;
    cursor: pointer;
    transition: all var(--transition);
  }

  .pill:hover {
    border-color: var(--color-purple);
  }

  .pill.on {
    background: var(--color-gold);
    border-color: var(--color-gold);
    color: var(--color-ink-on-accent);
  }

  .more {
    position: absolute;
    top: 0.6rem;
    right: 0.55rem;
    display: grid;
    place-items: center;
    width: 26px;
    height: 26px;
    padding: 0;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: 50%;
    color: var(--color-text-secondary);
    cursor: pointer;
  }

  .more:hover {
    color: var(--color-purple);
  }

  .more.open svg {
    transform: rotate(180deg);
  }

  .subcategories {
    padding: 0.5rem 0.55rem 0.6rem;
    border-bottom: 1px solid var(--color-border);
  }

  .label {
    margin-bottom: 0.35rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
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
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
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

  .subcategories .segmented button.on {
    background: var(--color-gold);
    color: var(--color-ink-on-accent);
  }

  .wr-seed.pending {
    visibility: hidden;
  }

  .wr-seed {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 0.8rem;
    padding: 0.55rem 0.7rem;
    border-bottom: 1px solid var(--color-border);
    background: color-mix(in srgb, var(--color-gold) 7%, transparent);
    box-shadow: inset 3px 0 0 var(--color-gold);
  }

  .wr-chip {
    color: var(--color-gold);
    border-color: color-mix(in srgb, var(--color-gold) 60%, transparent);
  }

  .wr-seed .seed {
    padding: 0.3rem 0.6rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text);
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    text-decoration: none;
  }

  .wr-seed a.seed:hover {
    color: var(--color-purple);
    border-color: var(--color-purple);
  }

  .wr-seed .seed.gone {
    color: var(--color-text-disabled);
    text-decoration: line-through;
  }

  .wr-time {
    color: var(--color-gold);
    font-size: 1.35rem;
  }

  .run-chip.blind {
    color: var(--color-success);
    border-color: color-mix(in srgb, var(--color-success) 60%, transparent);
  }

  .run-chip.replay {
    color: var(--color-purple);
    border-color: color-mix(in srgb, var(--color-purple) 60%, transparent);
  }

  .wr-runs {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .toolbar .segmented button.on {
    background: var(--color-surface-elevated);
    color: var(--color-text);
  }

  .toolbar {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.4rem;
    padding: 0.55rem;
    border-bottom: 1px solid var(--color-border);
  }

  .spacer {
    flex: 1;
  }

  .tool {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    padding: 0.38rem 0.7rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 600;
    cursor: pointer;
  }

  .tool:hover {
    border-color: var(--color-purple);
  }

  .tool.submit {
    background: var(--color-gold);
    border-color: var(--color-gold);
    color: var(--color-ink-on-accent);
  }

  .tool.submit:hover {
    background: var(--color-gold-hover);
    border-color: var(--color-gold-hover);
  }

  .filters {
    position: relative;
  }

  .popover {
    position: absolute;
    top: calc(100% + 0.35rem);
    left: 0;
    z-index: 5;
    display: flex;
    flex-direction: column;
    gap: 0.45rem;
    min-width: 12rem;
    padding: 0.7rem 0.8rem;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    font-size: var(--font-size-sm);
  }

  .popover label {
    display: flex;
    align-items: center;
    gap: 0.45rem;
    cursor: pointer;
  }

  .popover hr {
    width: 100%;
    margin: 0.1rem 0;
    border: none;
    border-top: 1px solid var(--color-border);
  }

  .rules {
    padding: 0.7rem 0.9rem;
    border-bottom: 1px solid var(--color-border);
    font-size: var(--font-size-sm);
  }

  .rules h4,
  .rules h5 {
    margin: 0 0 0.4rem;
    font-family: var(--font-display);
    letter-spacing: 0.04em;
    text-transform: uppercase;
  }

  .rules h4 {
    font-size: 1rem;
  }

  .rules h4:not(:first-child) {
    margin-top: 0.9rem;
  }

  .rules h5 {
    margin-top: 0.7rem;
    font-size: 0.85rem;
    color: var(--color-text-secondary);
  }

  .rules p {
    margin: 0 0 0.35rem;
  }

  .rules ul {
    margin: 0;
    padding-left: 1.2rem;
  }

  .muted {
    color: var(--color-text-secondary);
  }

  .content.stale {
    opacity: 0.55;
    transition: opacity var(--transition);
  }

  .message {
    margin: 0;
    padding: 1.2rem 0.9rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .message.error {
    color: var(--color-danger);
  }
</style>
