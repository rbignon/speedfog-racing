<script lang="ts">
  import { goto } from "$app/navigation";
  import { auth } from "$lib/stores/auth.svelte";
  import {
    fetchTrainingPools,
    fetchTrainingSessions,
    createTrainingSession,
    type PoolStats,
    type PoolInfo,
    type TrainingSession,
  } from "$lib/api";
  import PoolSettingsCard from "$lib/components/PoolSettingsCard.svelte";
  import PoolTabs from "$lib/components/PoolTabs.svelte";
  import SurveyBanner from "$lib/components/SurveyBanner.svelte";
  import TrainingSessionCard from "$lib/components/TrainingSessionCard.svelte";
  import { timeAgo } from "$lib/utils/time";
  import { formatPoolName } from "$lib/utils/format";
  import { formatIgt } from "$lib/utils/training";

  let pools: PoolStats = $state({});
  let sessions: TrainingSession[] = $state([]);
  let selectedPool = $state<string | null>(null);
  let loadingPools = $state(true);
  let loadingSessions = $state(true);
  let startingPool = $state<string | null>(null);
  let error = $state<string | null>(null);
  let authChecked = $state(false);

  let sortedPools = $derived(
    Object.entries(pools)
      .map(([p, info]) => [p, info] as [string, PoolInfo])
      .sort(
        (a, b) =>
          (a[1].pool_config?.sort_order ?? 99) -
            (b[1].pool_config?.sort_order ?? 99) || a[0].localeCompare(b[0]),
      ),
  );

  let selectedConfig = $derived(
    selectedPool ? (pools[selectedPool]?.pool_config ?? null) : null,
  );
  let selectedInfo = $derived(
    selectedPool ? (pools[selectedPool] ?? null) : null,
  );
  let activeSessions = $derived(sessions.filter((s) => s.status === "active"));

  // Recommend Sprint to new players (no sessions yet)
  let isNewPlayer = $derived(sessions.length === 0);
  let sprintPool = $derived(
    sortedPools.find(
      ([, info]) => info.pool_config?.name === "Sprint" && info.available > 0,
    )?.[0] ?? null,
  );

  $effect(() => {
    if (auth.initialized && !authChecked) {
      authChecked = true;

      if (!auth.isLoggedIn) {
        goto("/");
        return;
      }

      loadData();
    }
  });

  async function loadData() {
    try {
      const [poolData, sessionData] = await Promise.all([
        fetchTrainingPools(),
        fetchTrainingSessions(),
      ]);
      pools = poolData;
      sessions = sessionData;
      // Default to Sprint for new players, otherwise first available pool
      if (sprintPool && sessions.length === 0) {
        selectedPool = sprintPool;
      } else {
        const available = sortedPools.find(([, info]) => info.available > 0);
        if (available) selectedPool = available[0];
      }
    } catch (e) {
      console.error("Failed to load solo data:", e);
      error = "Failed to load solo data.";
    } finally {
      loadingPools = false;
      loadingSessions = false;
    }
  }

  async function startTraining(poolName: string) {
    startingPool = poolName;
    error = null;

    try {
      const session = await createTrainingSession(poolName);
      goto(`/training/${session.id}`);
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to start solo session.";
      startingPool = null;
      // Refresh sessions so UI reflects server state (e.g., 409 = active session exists)
      try {
        sessions = await fetchTrainingSessions();
      } catch {
        // ignore refresh failure
      }
    }
  }
</script>

<svelte:head>
  <title>Solo - SpeedFog Racing</title>
</svelte:head>

<main class="training-page">
  <h1>Solo</h1>
  <p class="subtitle">
    Run fresh seeds at your own pace. No race, no pressure.
  </p>

  {#if auth.user?.feedback_prompted_at}
    <SurveyBanner />
  {/if}

  {#if error}
    <div class="error-banner">
      {error}
      <button onclick={() => (error = null)}>&times;</button>
    </div>
  {/if}

  <!-- Active Sessions or Pool Selection -->
  <section class="section">
    {#if loadingPools || loadingSessions}
      <h2>Start a Run</h2>
      <p class="loading">Loading...</p>
    {:else if activeSessions.length > 0}
      <h2>Active Run{activeSessions.length > 1 ? "s" : ""}</h2>
      <div class="active-sessions">
        {#each activeSessions as session (session.id)}
          <TrainingSessionCard {session} />
        {/each}
      </div>
    {:else}
      <h2>Start a Run</h2>
      {#if sortedPools.length === 0}
        <p class="empty">No game modes available.</p>
      {:else}
        <div class="pool-container">
          <PoolTabs
            pools={sortedPools}
            selected={selectedPool}
            onselect={(p) => {
              if (!startingPool) selectedPool = p;
            }}
            disabled={startingPool !== null}
            recommended={isNewPlayer ? sprintPool : null}
          />
          {#if selectedPool && selectedConfig}
            <div class="pool-content">
              <PoolSettingsCard
                poolName={selectedConfig?.name || formatPoolName(selectedPool)}
                poolConfig={selectedConfig}
                compact
              />
              <p
                class="seed-count"
                class:pool-exhausted={selectedInfo?.played_by_user != null &&
                  selectedInfo.played_by_user >= (selectedInfo?.available ?? 0)}
              >
                {#if selectedInfo?.played_by_user != null && selectedInfo.played_by_user > 0}
                  {selectedInfo.played_by_user}/{selectedInfo.available} seed{selectedInfo.available !==
                  1
                    ? "s"
                    : ""} played
                  {#if selectedInfo.played_by_user >= selectedInfo.available}
                    (seeds will repeat)
                  {/if}
                {:else}
                  {selectedInfo?.available ?? 0} seed{(selectedInfo?.available ??
                    0) !== 1
                    ? "s"
                    : ""} available
                {/if}
              </p>
              <div class="pool-content-footer">
                <button
                  class="btn btn-primary"
                  disabled={(selectedInfo?.available ?? 0) === 0 ||
                    startingPool !== null}
                  onclick={() => startTraining(selectedPool!)}
                >
                  {#if startingPool === selectedPool}
                    Starting...
                  {:else}
                    Start
                  {/if}
                </button>
              </div>
            </div>
          {/if}
        </div>
      {/if}
    {/if}
  </section>

  <!-- History -->
  <section class="section">
    <h2>History</h2>
    {#if loadingSessions}
      <p class="loading">Loading sessions...</p>
    {:else if sessions.length === 0}
      <p class="empty">No solo sessions yet. Start a run above!</p>
    {:else}
      <div class="history-table-wrapper">
        <table class="history-table">
          <thead>
            <tr>
              <th>Mode</th>
              <th>Status</th>
              <th>Progress</th>
              <th>IGT</th>
              <th>Deaths</th>
              <th>Date</th>
            </tr>
          </thead>
          <tbody>
            {#each sessions as session}
              <tr>
                <td>
                  <a href="/training/{session.id}" class="session-link">
                    {session.pool_display_name ||
                      formatPoolName(session.pool_name)}
                  </a>
                </td>
                <td>
                  <span class="badge badge-{session.status}"
                    >{session.status}</span
                  >
                </td>
                <td class="mono"
                  >{Math.min(
                    session.current_layer + 1,
                    session.seed_total_layers ?? Infinity,
                  )}/{session.seed_total_layers ?? "?"}</td
                >
                <td class="mono">{formatIgt(session.igt_ms)}</td>
                <td class="mono">{session.death_count}</td>
                <td class="date">{timeAgo(session.created_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  </section>
</main>

<style>
  .training-page {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
    box-sizing: border-box;
  }

  h1 {
    color: var(--color-gold);
    font-size: var(--font-size-2xl);
    font-weight: 700;
    margin: 0 0 0.25rem;
  }

  .subtitle {
    color: var(--color-text-secondary);
    margin: 0 0 2rem;
  }

  .error-banner {
    background: var(--color-danger-dark);
    color: white;
    padding: 0.75rem 1rem;
    border-radius: var(--radius-md);
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
  }

  .error-banner button {
    background: none;
    border: none;
    color: white;
    font-size: 1.25rem;
    cursor: pointer;
  }

  .section {
    margin-bottom: 2.5rem;
  }

  h2 {
    color: var(--color-gold);
    font-size: var(--font-size-lg);
    font-weight: 600;
    margin: 0 0 1rem;
  }

  .loading {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .empty {
    color: var(--color-text-secondary);
  }

  /* Active session cards */
  .active-sessions {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
    max-width: 480px;
  }

  .pool-exhausted {
    color: var(--color-gold);
  }

  /* Pool container (tabs + content as one unit) */
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

  .pool-content-footer {
    display: flex;
    justify-content: flex-end;
    align-items: center;
    gap: 1rem;
  }

  .seed-count {
    margin: 0.75rem 0 0;
    font-size: var(--font-size-sm);
    color: var(--color-text-disabled);
  }

  /* History table */
  .history-table-wrapper {
    overflow-x: auto;
  }

  .history-table {
    width: 100%;
    border-collapse: collapse;
  }

  .history-table th {
    text-align: left;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
    padding: 0.5rem 0.75rem;
    border-bottom: 1px solid var(--color-border);
  }

  .history-table td {
    padding: 0.65rem 0.75rem;
    border-bottom: 1px solid var(--color-border);
    font-size: var(--font-size-sm);
  }

  .history-table tbody tr:hover {
    background: var(--color-surface);
  }

  .session-link {
    color: var(--color-text);
    text-decoration: none;
    font-weight: 500;
  }

  .session-link:hover {
    color: var(--color-purple);
  }

  .mono {
    font-variant-numeric: tabular-nums;
  }

  .date {
    color: var(--color-text-disabled);
  }

  @media (max-width: 640px) {
    .training-page {
      padding: 1rem;
    }
  }
</style>
