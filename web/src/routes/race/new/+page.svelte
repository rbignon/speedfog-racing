<script lang="ts">
  import { untrack } from "svelte";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { auth } from "$lib/stores/auth.svelte";
  import {
    createRace,
    fetchPoolStats,
    fetchSpeedrunSeedSummary,
    type PoolStats,
    type PoolInfo,
    type SpeedrunSeedSummary,
  } from "$lib/api";
  import PoolSettingsCard from "$lib/components/PoolSettingsCard.svelte";
  import PoolTabs from "$lib/components/PoolTabs.svelte";
  import DateTimePicker from "$lib/components/DateTimePicker.svelte";
  import SpeedrunRules from "$lib/components/stats/speedrun/SpeedrunRules.svelte";
  import { formatPoolName } from "$lib/utils/format";
  import { raceItemsAvailability } from "$lib/raceItems";
  import {
    parseRaceNewParams,
    seedPageHref,
    startRunHref,
  } from "$lib/speedrun";

  // `?seed=<n>` makes a Set Seed race on that seed, `?mode=speedrun` turns
  // the Speedrun option on and `?pool=` picks the pool. Applied on arrival
  // (see the effect below); what the organizer changes afterwards stays
  // theirs.
  let asked = $derived(parseRaceNewParams(page.url.searchParams));
  let setSeed = $derived(asked.seed);

  let name = $state("");
  let scheduledAt = $state("");
  let poolName = $state("standard");
  let organizerParticipates = $state(true);
  let isPublic = $state(true);
  let openRegistration = $state(true);
  let maxParticipants = $state(30);
  let lateJoinEnabled = $state(true);
  let autoEndEnabled = $state(false);
  let lateJoinWindowMinutes = $state(30);
  let raceDurationMinutes = $state(120);
  let deathless = $state(false);
  let raceItems = $state(false);
  let privateDag = $state(false);
  let customRules = $state("");
  let speedrun = $state(untrack(() => asked.speedrun));
  // A Set Seed race's seed, as the server knows it; the lookup's error text
  // ("Unknown seed", "Ambiguous seed ID") otherwise.
  let seedSummary = $state<SpeedrunSeedSummary | null>(null);
  let seedError = $state<string | null>(null);
  let showAdvanced = $state(false);
  let pools: PoolStats = $state({});
  let loading = $state(true);
  let creating = $state(false);
  let error = $state<string | null>(null);
  let authChecked = $state(false);

  // Seeds this race could draw: a normal race also takes SEEN seeds (seeds
  // put aside before their race started), a speedrun race never does, and
  // leaves the pool's speedrun floor in reserve.
  function drawable(info: PoolInfo): number {
    return speedrun
      ? Math.max(0, info.available - info.speedrun_floor)
      : info.available + info.seen;
  }

  // `available` holds the drawable count, which the tabs gate on.
  let sortedPools = $derived(
    Object.entries(pools)
      .map(
        ([p, info]) =>
          [p, { ...info, available: drawable(info) }] as [string, PoolInfo],
      )
      .sort(
        (a, b) =>
          (a[1].pool_config?.sort_order ?? 99) -
            (b[1].pool_config?.sort_order ?? 99) || a[0].localeCompare(b[0]),
      ),
  );

  let hasAvailablePool = $derived(
    sortedPools.some(([, info]) => info.available > 0),
  );
  let selectedConfig = $derived(pools[poolName]?.pool_config ?? null);
  let selectedAvailable = $derived(
    pools[poolName] ? drawable(pools[poolName]) : 0,
  );
  // At or under its floor, a pool gives a normal race a SEEN seed first,
  // which counts on no Speedrun board: say so before the race exists.
  let drawsSeenSeed = $derived(
    !speedrun &&
      pools[poolName] !== undefined &&
      pools[poolName].seen > 0 &&
      pools[poolName].available <= pools[poolName].speedrun_floor,
  );
  // A Set Seed race takes its pool from the seed, which need not be listed
  // (a retired category's seed stays replayable): no card then.
  let seedConfig = $derived(
    seedSummary ? (pools[seedSummary.category]?.pool_config ?? null) : null,
  );
  // The game mode a Speedrun or Set Seed race's name suggestion names: the
  // selected pool, or the seed's category as the server names it (its pool
  // need not be listed).
  let suggestedPool = $derived(
    setSeed !== null
      ? (seedSummary?.category_name ?? null)
      : speedrun
        ? selectedConfig?.name || formatPoolName(poolName)
        : null,
  );
  // A Set Seed race draws nothing from the pools: it only needs its seed.
  // Otherwise the selected pool itself must have something to draw (another
  // pool having seeds is not enough once the Speedrun option hides seen ones).
  let canCreate = $derived(
    setSeed === null
      ? hasAvailablePool && selectedAvailable > 0
      : seedSummary?.replayable === true,
  );

  // The option needs a normal race on a pool holding plugin seeds; a
  // ticked box that stops qualifying (mode or pool switch) is not sent.
  let raceItemsAvail = $derived(
    raceItemsAvailability(
      setSeed === null && !speedrun ? "normal" : "other",
      pools[poolName],
    ),
  );
  let raceItemsOn = $derived(raceItems && raceItemsAvail.enabled);

  // Advanced-options state grid shown inside the trigger: one entry per
  // option, checked when the option is active for this race (actual
  // state, not deviation from defaults, so "late joiners" starts checked).
  let advancedOptions = $derived([
    { label: "late joiners", active: lateJoinEnabled },
    { label: "auto-end", active: autoEndEnabled },
    { label: "deathless", active: deathless },
    { label: "race items", active: raceItemsOn },
    { label: "private map", active: privateDag },
    { label: "custom rules", active: customRules.trim() !== "" },
    // A Set Seed race's mode is set by its seed.
    ...(setSeed === null ? [{ label: "speedrun", active: speedrun }] : []),
  ]);

  $effect(() => {
    if (auth.initialized && !authChecked) {
      authChecked = true;

      if (!auth.isLoggedIn || !auth.canCreateRace) {
        goto("/");
        return;
      }

      loadPools();
    }
  });

  // The URL's request, applied on arrival and again when a link to
  // /race/new with other parameters reuses this page (the navbar's Create
  // Race, from a Set Seed race form).
  let appliedSearch: string | null = null;
  $effect(() => {
    const search = page.url.search;
    if (search === appliedSearch) return;
    appliedSearch = search;
    untrack(() => {
      speedrun = asked.speedrun;
      seedSummary = null;
      seedError = null;
      if (asked.seed !== null) loadSeed(asked.seed);
      pickPool();
    });
  });

  async function loadSeed(seed: string) {
    try {
      const summary = await fetchSpeedrunSeedSummary(seed);
      if (asked.seed === seed) seedSummary = summary;
    } catch (e) {
      if (asked.seed === seed)
        seedError = e instanceof Error ? e.message : "Unknown seed";
    }
  }

  // The asked pool when it has seeds, else the first pool with seeds.
  function pickPool() {
    const available =
      sortedPools.find(([p, info]) => p === asked.pool && info.available > 0) ??
      sortedPools.find(([, info]) => info.available > 0);
    if (available) poolName = available[0];
  }

  async function loadPools() {
    try {
      pools = await fetchPoolStats();
      pickPool();
    } catch (e) {
      console.error("Failed to fetch pools:", e);
      error = "Failed to load game modes.";
    } finally {
      loading = false;
    }
  }

  async function handleSubmit(e: Event) {
    e.preventDefault();
    if (!name.trim()) {
      error = "Please enter a race name.";
      return;
    }
    if (isPublic && !scheduledAt) {
      error = "Public races must have a scheduled time.";
      return;
    }
    if (!canCreate) return;

    creating = true;
    error = null;

    try {
      const isoScheduled = scheduledAt || null;
      const race = await createRace(
        name.trim(),
        seedSummary?.category ?? poolName,
        organizerParticipates,
        {},
        isoScheduled,
        isPublic,
        openRegistration,
        openRegistration ? maxParticipants : null,
        lateJoinEnabled ? lateJoinWindowMinutes : null,
        autoEndEnabled ? raceDurationMinutes : null,
        privateDag,
        customRules.trim() || null,
        deathless,
        seedSummary ? "set_seed" : speedrun ? "speedrun" : "normal",
        seedSummary?.seed_number ?? null,
        raceItemsOn,
      );
      goto(`/race/${race.id}`);
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to create race.";
      creating = false;
    }
  }
</script>

<svelte:head>
  <title>Create Race - SpeedFog Racing</title>
</svelte:head>

<main>
  <div class="page-header">
    <h1>
      {setSeed !== null
        ? "Create Set Seed Race"
        : speedrun
          ? "Create Speedrun Race"
          : "Create Race"}
    </h1>
    {#if setSeed !== null}
      {#if seedSummary}
        <a class="seed-badge" href={seedPageHref(seedSummary.seed_number)}
          >Seed {seedSummary.seed_number}</a
        >
      {:else}
        <span class="seed-badge">Seed {setSeed}</span>
      {/if}
    {/if}
  </div>

  {#if loading}
    <p class="loading">Loading...</p>
  {:else}
    {#if setSeed !== null}
      <section class="set-seed-banner">
        <div class="banner-head">
          {#if seedSummary}
            <span class="banner-category">{seedSummary.category_name}</span>
          {/if}
          <a
            class="banner-change"
            href={startRunHref(
              seedSummary?.category ?? null,
              seedSummary?.seed_number ?? setSeed,
            )}>Change seed</a
          >
        </div>
        {#if seedError}
          <p class="banner-reason">{seedError}</p>
        {:else if seedSummary && !seedSummary.replayable}
          <p class="banner-reason">{seedSummary.not_replayable_reason}</p>
        {:else if seedSummary}
          <p>
            Runners may already know this seed. Times count on the
            <strong>{seedSummary.category_name} - Set Seed</strong> board only.
          </p>
          <SpeedrunRules />
        {/if}
      </section>
    {/if}

    <form onsubmit={handleSubmit}>
      <div class="form-group">
        <label for="name">Race Name</label>
        <input
          type="text"
          id="name"
          bind:value={name}
          placeholder={suggestedPool
            ? `e.g. ${suggestedPool} Grinding`
            : "e.g. Sunday Showdown"}
          disabled={creating}
          required
        />
      </div>

      <div class="form-group">
        <span>Game Mode</span>
        {#if setSeed !== null}
          <!-- The seed sets the pool: no mode grid, no Speedrun option. -->
          <div class="pool-container">
            <div class="seed-mode">
              {#if seedSummary}
                <strong>{seedSummary.category_name}</strong>, set by the seed
              {:else}
                Set by the seed
              {/if}
            </div>
            <div class="pool-content">
              {#if seedSummary && seedConfig}
                <PoolSettingsCard
                  poolName={seedSummary.category}
                  poolConfig={seedConfig}
                  compact
                />
              {/if}
              <p class="seeds-available">
                Seed {seedSummary?.seed_number ?? setSeed}, fixed: no reroll
              </p>
            </div>
          </div>
        {:else if sortedPools.length === 0}
          <p class="empty-pools">
            No game modes available. Seeds need to be generated before races can
            be created.
          </p>
        {:else}
          <div class="pool-container">
            <PoolTabs
              pools={sortedPools}
              selected={poolName}
              onselect={(p) => {
                if (!creating) poolName = p;
              }}
              disabled={creating}
            />
            {#if hasAvailablePool && selectedConfig}
              <div class="pool-content">
                <PoolSettingsCard
                  {poolName}
                  poolConfig={selectedConfig}
                  compact
                />
                <p class="seeds-available">
                  {#if speedrun && selectedAvailable === 0}
                    No fresh seed right now
                  {:else}
                    {selectedAvailable} seed{selectedAvailable !== 1 ? "s" : ""} available
                  {/if}
                </p>
                {#if drawsSeenSeed}
                  <p class="seen-seed-warning">
                    Low on fresh seeds right now: this race would get a seed
                    another race gave up, whose map may be known, so it would
                    not count on the Speedrun boards.
                  </p>
                {/if}
              </div>
            {/if}
          </div>
          {#if !hasAvailablePool}
            <p class="empty-pools">
              {#if speedrun}
                No fresh seed right now in any game mode.
              {:else}
                No seeds available in any game mode. New seeds need to be
                generated.
              {/if}
            </p>
          {/if}
        {/if}
      </div>

      <div class="form-group">
        <label for="scheduled">
          Scheduled Time
          {#if isPublic}
            <span class="required">(required)</span>
          {:else}
            <span class="optional">(optional)</span>
          {/if}
        </label>
        <DateTimePicker
          value={scheduledAt}
          onchange={(iso) => (scheduledAt = iso)}
          min={new Date()}
          disabled={creating}
          placeholder="Pick a date"
        />
        <p class="hint">
          Indicative only. The organizer starts the race manually at any time.
        </p>
      </div>

      <div class="form-group role-visibility-grid">
        <div class="role-col">
          <span>Your role</span>
          <div class="radio-group">
            <label class="radio-label">
              <input
                type="radio"
                name="participate"
                checked={organizerParticipates}
                onchange={() => (organizerParticipates = true)}
                disabled={creating}
              />
              I'll race
            </label>
            <label class="radio-label">
              <input
                type="radio"
                name="participate"
                checked={!organizerParticipates}
                onchange={() => (organizerParticipates = false)}
                disabled={creating}
              />
              Organize only
            </label>
          </div>
          <p class="hint">
            If you choose "Organize only", you will see the metro map and cannot
            join as a player later.
          </p>
        </div>

        <div class="visibility-col">
          <span>Visibility</span>
          <div class="radio-group">
            <label class="radio-label">
              <input
                type="radio"
                name="visibility"
                checked={isPublic}
                onchange={() => (isPublic = true)}
                disabled={creating}
              />
              Public
            </label>
            <label class="radio-label">
              <input
                type="radio"
                name="visibility"
                checked={!isPublic}
                onchange={() => (isPublic = false)}
                disabled={creating}
              />
              Private
            </label>
          </div>
          <p class="hint">
            {#if isPublic}
              Announced on Discord and listed on the homepage so players can
              find and join.
            {:else}
              Hidden from the homepage. Players can still join via direct link
              or invite.
            {/if}
          </p>
        </div>
      </div>

      <div class="form-group">
        <span>Registration</span>
        <div class="registration-row">
          <label class="radio-label">
            <input
              type="radio"
              name="registration"
              checked={!openRegistration}
              onchange={() => (openRegistration = false)}
              disabled={creating}
            />
            Invite only
          </label>
          <label class="radio-label">
            <input
              type="radio"
              name="registration"
              checked={openRegistration}
              onchange={() => (openRegistration = true)}
              disabled={creating}
            />
            Open
          </label>
          {#if openRegistration}
            <label class="inline-max">
              max
              <input
                type="number"
                bind:value={maxParticipants}
                min="2"
                max="100"
                disabled={creating}
              />
            </label>
          {/if}
        </div>
        <p class="hint">
          Open registration lets any logged-in player join the race themselves.
        </p>
      </div>

      <div class="advanced">
        <button
          type="button"
          class="advanced-trigger"
          onclick={() => (showAdvanced = !showAdvanced)}
          disabled={creating}
          aria-expanded={showAdvanced}
          aria-controls="advanced-panel"
        >
          <span class="advanced-header">
            <span class="advanced-chevron">{showAdvanced ? "▼" : "▸"}</span>
            <span class="advanced-label">Advanced options</span>
          </span>
          <span class="advanced-summary-grid">
            {#each advancedOptions as opt (opt.label)}
              <span class="advanced-option" class:active={opt.active}>
                <span class="advanced-option-check"
                  >{opt.active ? "✓" : ""}</span
                >
                {opt.label}
              </span>
            {/each}
          </span>
        </button>

        {#if showAdvanced}
          <div id="advanced-panel" class="advanced-panel">
            <div class="form-group">
              <span>Late joiners</span>
              <label class="radio-label">
                <input
                  type="checkbox"
                  bind:checked={lateJoinEnabled}
                  disabled={creating}
                />
                Allow joining up to
                {#if lateJoinEnabled}
                  <input
                    type="number"
                    bind:value={lateJoinWindowMinutes}
                    min="1"
                    max={autoEndEnabled ? raceDurationMinutes : undefined}
                    disabled={creating}
                    class="inline-duration"
                  />
                  min after start
                {/if}
              </label>
              <p class="hint">
                Counted from the actual start time. The map stays hidden from
                non-participants until the window closes.
              </p>
            </div>

            <div class="form-group">
              <span>Auto-end</span>
              <label class="radio-label">
                <input
                  type="checkbox"
                  bind:checked={autoEndEnabled}
                  disabled={creating}
                />
                End race automatically after
                {#if autoEndEnabled}
                  <input
                    type="number"
                    bind:value={raceDurationMinutes}
                    min="1"
                    disabled={creating}
                    class="inline-duration"
                  />
                  min
                {/if}
              </label>
              <p class="hint">
                Useful for time-boxed community races. The organizer can still
                finalize earlier.
              </p>
            </div>

            <div class="form-group">
              <span>Deathless</span>
              <label class="radio-label">
                <input
                  type="checkbox"
                  bind:checked={deathless}
                  disabled={creating}
                />
                Eliminate players on their first death
              </label>
              <p class="hint">
                A player who dies is automatically marked as abandoned.
              </p>
            </div>

            {#if setSeed === null && !speedrun}
              <div class="form-group">
                <span>Race items</span>
                <label class="radio-label">
                  <input
                    type="checkbox"
                    bind:checked={raceItems}
                    disabled={creating || !raceItemsAvail.enabled}
                  />
                  Boss kills give Mario Kart style items
                </label>
                <p class="hint">
                  Items hit other runners. Items races do not count on the
                  Speedrun boards or the community stats.
                </p>
                {#if raceItemsAvail.hint}
                  <p class="hint">{raceItemsAvail.hint}</p>
                {/if}
              </div>
            {/if}

            <div class="form-group">
              <span>Spoiler protection</span>
              <label class="radio-label">
                <input
                  type="checkbox"
                  bind:checked={privateDag}
                  disabled={creating}
                />
                Hide the map from non-participants until the race finishes
              </label>
              <p class="hint">
                Useful for asynchronous races where spoilers matter.
              </p>
            </div>

            <div class="form-group">
              <label for="custom-rules">Custom rules</label>
              <textarea
                id="custom-rules"
                bind:value={customRules}
                maxlength="1000"
                rows="4"
                placeholder="One rule per line"
                disabled={creating}
              ></textarea>
              <p class="hint">
                Shown to players in the download popup and on the race page. One
                rule per line.
              </p>
            </div>

            {#if setSeed === null}
              <div class="form-group">
                <span>Speedrun</span>
                <label class="radio-label">
                  <input
                    type="checkbox"
                    bind:checked={speedrun}
                    disabled={creating}
                  />
                  Speedrun race
                </label>
                <p class="hint">
                  Always a fresh seed and no reset, so the race counts on the
                  Speedrun boards; a seed re-roll asks for a reason, sent to the
                  admins. The game modes above then count only the fresh seeds a
                  speedrun race can draw.
                </p>
              </div>
            {/if}
          </div>
        {/if}
      </div>

      {#if error}
        <div class="error" role="alert">{error}</div>
      {/if}

      <div class="actions">
        <button
          type="submit"
          class="btn btn-primary"
          disabled={creating || !canCreate}
        >
          {creating ? "Creating..." : "Create Race"}
        </button>
        <button
          type="button"
          class="btn btn-secondary"
          onclick={() => goto("/races")}
          disabled={creating}
        >
          Cancel
        </button>
      </div>
    </form>
  {/if}
</main>

<style>
  main {
    max-width: 600px;
    margin: 0 auto;
    padding: 2rem;
  }

  .page-header {
    display: flex;
    flex-wrap: wrap;
    justify-content: space-between;
    align-items: center;
    gap: 0.5rem 1rem;
    margin-bottom: 2rem;
  }

  h1 {
    margin: 0;
    color: var(--color-text);
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
  }

  a.seed-badge:hover {
    color: var(--color-purple-hover);
  }

  .seed-badge {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.2rem 0.5rem;
    color: var(--color-text-secondary);
  }

  form {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .form-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .form-group > :is(label, span):first-child {
    font-family: var(--font-mono);
    font-weight: 500;
    font-size: 0.7rem;
    letter-spacing: 0.09em;
    color: var(--color-text-secondary);
    text-transform: uppercase;
  }

  input[type="text"] {
    padding: 0.75rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: 1rem;
  }

  input[type="text"]:focus {
    outline: none;
    border-color: var(--color-purple);
  }

  input[type="text"]:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  textarea {
    width: 100%;
    background: var(--color-bg);
    color: var(--color-text);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.5rem 0.75rem;
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    resize: vertical;
  }

  textarea:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .optional {
    font-weight: 400;
    text-transform: none;
    letter-spacing: normal;
    color: var(--color-text-disabled);
  }

  .required {
    font-weight: 400;
    text-transform: none;
    letter-spacing: normal;
    color: var(--color-purple);
  }

  .pool-container {
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
  }

  .pool-content {
    padding: 1rem;
    background: var(--color-surface-elevated);
  }

  .pool-content > :global(.card) {
    background: transparent;
    border-radius: 0;
    padding: 0;
  }

  .seeds-available {
    margin: 0.75rem 0 0;
    color: var(--color-text-disabled);
    font-size: var(--font-size-sm);
  }

  .seeds-available:first-child {
    margin-top: 0;
  }

  /* Styled like the race page's notice for a race that counts on no board. */
  .seen-seed-warning {
    margin: 0.75rem 0 0;
    padding: 0.5rem 1rem;
    border-left: 3px solid var(--color-text-secondary);
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  /* A Set Seed race: the seed's banner over the form. */
  .set-seed-banner {
    display: flex;
    flex-direction: column;
    gap: 0.6rem;
    margin: 0 0 1.5rem;
    padding: 1.1rem 1.3rem;
    background: var(--color-surface);
    border-left: 3px solid var(--color-gold);
    border-radius: var(--radius-md);
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .set-seed-banner p {
    margin: 0;
    line-height: 1.6;
  }

  .set-seed-banner strong {
    color: var(--color-gold);
  }

  .banner-head {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.5rem 0.7rem;
  }

  .banner-change {
    margin-left: auto;
    color: var(--color-purple);
    text-decoration: none;
  }

  .banner-change:hover {
    color: var(--color-purple-hover);
  }

  .banner-category {
    color: var(--color-text);
    font-weight: 600;
  }

  .set-seed-banner .banner-reason {
    color: var(--color-danger);
  }

  .seed-mode {
    padding: 0.7rem 0.9rem;
    background: var(--color-surface);
    border-radius: var(--radius-lg) var(--radius-lg) 0 0;
    border-bottom: 1px solid var(--color-border);
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .seed-mode strong {
    color: var(--color-text);
  }

  .radio-group {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .radio-label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    font-size: 1rem;
    font-weight: normal;
    color: var(--color-text);
    text-transform: none;
    letter-spacing: normal;
  }

  .empty-pools {
    color: var(--color-text-disabled);
    font-style: italic;
    margin: 0;
    padding: 1rem;
    background: var(--color-surface);
    border-radius: var(--radius-sm);
    border: 1px dashed var(--color-border);
  }

  .hint {
    color: var(--color-text-disabled);
    font-size: var(--font-size-sm);
    margin: 0;
    line-height: 1.4;
  }

  .role-visibility-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 1.25rem;
  }

  .role-col,
  .visibility-col {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .role-col > span:first-child,
  .visibility-col > span:first-child {
    font-family: var(--font-mono);
    font-weight: 500;
    font-size: 0.7rem;
    letter-spacing: 0.09em;
    color: var(--color-text-secondary);
    text-transform: uppercase;
  }

  .registration-row {
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.75rem;
  }

  .inline-max {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    font-size: 1rem;
    font-weight: normal;
    color: var(--color-text);
  }

  .inline-max input[type="number"] {
    width: 70px;
    padding: 0.5rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: 1rem;
  }

  .inline-max input[type="number"]:focus {
    outline: none;
    border-color: var(--color-purple);
  }

  .actions {
    display: flex;
    gap: 0.75rem;
    align-self: flex-start;
  }

  .inline-duration {
    width: 70px;
    padding: 0.35rem 0.5rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: 1rem;
    margin: 0 0.25rem;
  }

  .inline-duration:focus {
    outline: none;
    border-color: var(--color-purple);
  }

  .advanced {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .advanced-trigger {
    display: flex;
    flex-direction: column;
    align-items: stretch;
    gap: 0.5rem;
    padding: 0.75rem 1rem;
    background: transparent;
    border: 1px dashed var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    text-align: left;
    cursor: pointer;
  }

  .advanced-trigger:hover:not(:disabled) {
    border-color: var(--color-purple);
  }

  .advanced-trigger:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .advanced-chevron {
    color: var(--color-purple);
  }

  .advanced-label {
    font-weight: 500;
  }

  .advanced-header {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .advanced-summary-grid {
    display: grid;
    grid-template-columns: repeat(2, 1fr);
    gap: 0.15rem 1rem;
    padding-left: 1.25rem;
    color: var(--color-text-disabled);
  }

  .advanced-option {
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }

  .advanced-option.active {
    color: var(--color-text);
  }

  .advanced-option-check {
    width: 1em;
    color: var(--color-success);
    text-align: center;
  }

  .advanced-panel {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
    padding-left: 1rem;
    border-left: 2px solid rgba(169, 155, 201, 0.3);
  }

  .error {
    background: rgba(220, 38, 38, 0.15);
    border: 1px solid var(--color-danger-dark);
    color: var(--color-danger);
    padding: 0.75rem 1rem;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-sm);
  }

  .loading {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  @media (max-width: 640px) {
    main {
      padding: 1rem;
    }

    h1 {
      font-size: var(--font-size-xl);
    }

    .role-visibility-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
