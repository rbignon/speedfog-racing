<script lang="ts">
  import { untrack } from "svelte";
  import { page } from "$app/state";
  import { auth } from "$lib/stores/auth.svelte";
  import { getEffectiveLocale } from "$lib/stores/locale.svelte";
  import { trainingStore } from "$lib/stores/training.svelte";
  import {
    fetchTrainingSession,
    abandonTrainingSession,
    downloadTrainingPack,
    fetchTrainingGhosts,
    type TrainingSessionDetail,
    type Ghost,
  } from "$lib/api";
  import { MetroDag, MetroDagProgressive, MetroDagFull } from "$lib/dag";
  import TrainingReplay from "$lib/replay/TrainingReplay.svelte";
  import ShareButtons from "$lib/components/ShareButtons.svelte";
  import ConfirmModal from "$lib/components/ConfirmModal.svelte";
  import ObsOverlayModal from "$lib/components/ObsOverlayModal.svelte";
  import FeedbackModal from "$lib/components/FeedbackModal.svelte";
  import PoolSettingsCard from "$lib/components/PoolSettingsCard.svelte";
  import DownloadModal from "$lib/components/DownloadModal.svelte";
  import TipTicker from "$lib/components/TipTicker.svelte";
  import ZoneSheet from "$lib/components/ZoneSheet.svelte";
  import { CONTENT_ITEMS } from "$lib/content/items";
  import { formatPoolName } from "$lib/utils/format";
  import { formatIgt } from "$lib/utils/training";
  import { statusLabel } from "$lib/format";

  function formatDatetime(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit",
    });
  }

  let sessionId = $derived(page.params.id!);
  let session = $state<TrainingSessionDetail | null>(null);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let showFullDag = $state(false);
  let abandoning = $state(false);
  let downloading = $state(false);
  let showAbandonConfirm = $state(false);
  let showObsModal = $state(false);
  let showFeedback = $state(false);
  let showDownloadModal = $state(false);
  let ghosts = $state<Ghost[]>([]);
  let dagView = $state<"map" | "replay">("map");
  let zoneSheetTarget = $state<{
    nodeId: string;
    displayName: string;
    zones: string[];
  } | null>(null);

  function openZoneCodex(nodeId: string, displayName: string, zones: string[]) {
    zoneSheetTarget = { nodeId, displayName, zones };
  }

  function closeZoneSheet() {
    zoneSheetTarget = null;
  }

  function handleWindowKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && zoneSheetTarget) {
      closeZoneSheet();
    }
  }

  // Move focus into the drawer when it opens (closed -> open transition
  // only, so retargeting while it is already open doesn't yank focus away
  // from ZoneSheet's own content).
  let drawerEl: HTMLDivElement | undefined = $state();
  let drawerWasOpen = false;
  $effect(() => {
    if (zoneSheetTarget && !drawerWasOpen) {
      drawerEl?.focus();
    }
    drawerWasOpen = zoneSheetTarget !== null;
  });

  const starterTips = CONTENT_ITEMS.filter(
    (i) => i.kind === "tip" && i.level === "beginner",
  )
    .slice(0, 4)
    .map((i) => i.short);

  // Live data from WS
  let liveParticipant = $derived(trainingStore.participant);
  let liveRace = $derived(trainingStore.race);

  let status = $derived(
    liveRace?.status === "finished"
      ? "finished"
      : (session?.status ?? "active"),
  );
  let igtMs = $derived(liveParticipant?.igt_ms ?? session?.igt_ms ?? 0);
  let deathCount = $derived(
    liveParticipant?.death_count ?? session?.death_count ?? 0,
  );
  let currentLayer = $derived(liveParticipant?.current_layer ?? 0);
  let totalLayers = $derived(session?.seed_total_layers ?? 0);
  let wsError = $derived(trainingStore.wsError);

  let isOwner = $derived(
    auth.isLoggedIn && session?.user?.id === auth.user?.id,
  );

  let graphJson = $derived(
    trainingStore.seed?.graph_json ?? session?.graph_json ?? null,
  );

  // Build a WsParticipant-compatible object for DAG components.
  // Prefer live WS data; fall back to static session data (abandoned/finished without WS).
  let dagParticipants = $derived.by(() => {
    if (liveParticipant) return [liveParticipant];
    if (!session || !session.zone_history || session.zone_history.length === 0)
      return [];
    return [
      {
        id: session.id,
        twitch_username: session.user?.twitch_username ?? "",
        twitch_display_name: session.user?.twitch_display_name ?? null,
        status: session.status === "active" ? "playing" : session.status,
        current_zone:
          session.zone_history[session.zone_history.length - 1]?.node_id ??
          null,
        current_layer: session.current_layer ?? 0,
        igt_ms: session.igt_ms,
        death_count: session.death_count,
        color_index: 0,
        mod_connected: false,
        zone_history: session.zone_history,
      },
    ];
  });

  let ghostParticipants = $derived.by(() => {
    return ghosts.map((g, i) => ({
      id: `ghost-${i}`,
      twitch_username: `Ghost ${i + 1}`,
      twitch_display_name: null,
      status: "finished" as const,
      current_zone: g.zone_history[g.zone_history.length - 1]?.node_id ?? null,
      current_layer: 0,
      igt_ms: g.igt_ms,
      death_count: g.death_count,
      color_index: 0,
      mod_connected: false,
      zone_history: g.zone_history,
    }));
  });

  $effect(() => {
    if (!auth.initialized) return;

    // Read locale outside reactive tracking: locale changes mid-session
    // should not trigger a WS reconnect cycle.
    const locale = untrack(() => getEffectiveLocale());
    loadSession();
    trainingStore.connect(sessionId, locale);

    return () => {
      trainingStore.disconnect();
    };
  });

  async function loadSession() {
    try {
      session = await fetchTrainingSession(sessionId);
      // Fetch ghosts in background for finished sessions
      if (session.status === "finished") {
        fetchTrainingGhosts(sessionId)
          .then((g) => {
            ghosts = g;
          })
          .catch(() => {});
      }
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load session.";
    } finally {
      loading = false;
    }
  }

  async function handleAbandon() {
    abandoning = true;
    error = null;
    try {
      session = await abandonTrainingSession(sessionId);
      showAbandonConfirm = false;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to abandon session.";
      showAbandonConfirm = false;
    } finally {
      abandoning = false;
    }
  }

  async function handleDownload() {
    downloading = true;
    error = null;
    try {
      await downloadTrainingPack(sessionId);
    } catch (e) {
      error = e instanceof Error ? e.message : "Download failed.";
    } finally {
      downloading = false;
    }
  }
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<svelte:head>
  <title>
    {session
      ? `Solo - ${session.pool_config?.name || formatPoolName(session.pool_name)}`
      : "Solo"} - SpeedFog Racing
  </title>
  <meta name="robots" content="noindex" />
</svelte:head>

<main class="training-detail">
  {#if wsError}
    <div class="ws-error">
      <h2>
        {#if wsError.code === 4004}
          Training session not found
        {:else if wsError.code === 4003}
          Authentication error
        {:else}
          Connection error
        {/if}
      </h2>
      <p class="ws-error-detail">{wsError.reason}</p>
      <a href="/training" class="btn btn-primary">Back to training</a>
    </div>
  {:else if loading}
    <p class="loading">Loading session...</p>
  {:else if error && !session}
    <div class="error-state">
      <p>{error}</p>
      <a href="/training" class="btn btn-secondary">Back to Solo</a>
    </div>
  {:else if session}
    <!-- Header -->
    <div class="header">
      <div class="header-left">
        <a href="/training" class="back-link">&larr; Solo</a>
        <h1>
          {session.pool_config?.name || formatPoolName(session.pool_name)}
        </h1>
        {#if session.user}
          <span class="player-name">
            by
            <a href="/user/{session.user.twitch_username}" class="player-link">
              {#if session.user.twitch_avatar_url}
                <img
                  src={session.user.twitch_avatar_url}
                  alt=""
                  class="player-avatar"
                />
              {/if}
              {session.user.twitch_display_name || session.user.twitch_username}
            </a>
          </span>
        {/if}
      </div>
      <div class="header-right">
        <ShareButtons />
        {#if auth.isLoggedIn}
          <button
            type="button"
            class="btn btn-secondary btn-sm"
            onclick={() => (showFeedback = true)}
          >
            Feedback
          </button>
        {/if}
        {#if session.seed_number}
          <span class="seed-badge">Seed {session.seed_number}</span>
        {/if}
        <span class="badge badge-{status}">{status}</span>
      </div>
    </div>

    {#if error}
      <div class="error-banner">
        {error}
        <button onclick={() => (error = null)}>&times;</button>
      </div>
    {/if}

    <!-- Stats bar -->
    <div class="stats-bar">
      <div class="stat">
        <span class="stat-label">IGT</span>
        <span class="stat-value mono">{formatIgt(igtMs)}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Deaths</span>
        <span class="stat-value mono">{deathCount}</span>
      </div>
      <div class="stat">
        <span class="stat-label">Progress</span>
        <span class="stat-value mono"
          >{Math.min(
            currentLayer + 1,
            totalLayers || Infinity,
          )}/{totalLayers}</span
        >
      </div>
      <div class="stat stat-right">
        <span class="stat-label">Started</span>
        <span class="stat-value stat-date"
          >{formatDatetime(session.created_at)}</span
        >
      </div>
      {#if session.finished_at}
        <div class="stat">
          <span class="stat-label">{statusLabel(session.status)}</span>
          <span class="stat-value stat-date"
            >{formatDatetime(session.finished_at)}</span
          >
        </div>
      {/if}
      {#if liveParticipant?.mod_connected}
        <div class="stat">
          <span class="stat-label">Live</span>
          <span class="stat-value connected-dot">&#x25CF;</span>
        </div>
      {/if}
    </div>

    <!-- Actions (owner only) -->
    {#if isOwner}
      <div class="actions">
        {#if status === "active"}
          <button
            class="btn btn-secondary"
            disabled={downloading}
            onclick={() => (showDownloadModal = true)}
          >
            {downloading ? "Preparing..." : "Download Pack"}
          </button>
        {/if}

        {#if status === "active"}
          <button
            class="btn btn-danger"
            onclick={() => (showAbandonConfirm = true)}
          >
            Abandon
          </button>
        {/if}
      </div>
    {/if}

    {#if status === "active" && !liveParticipant?.mod_connected}
      <div class="tip-banner">
        <TipTicker poolName={session.pool_name} variant="banner" />
      </div>
    {/if}

    <!-- DAG section -->
    {#if graphJson}
      <section class="dag-section">
        {#if status === "finished" && dagParticipants.length > 0}
          <div class="dag-view-toggle">
            <button
              class="toggle-btn"
              class:active={dagView === "map"}
              onclick={() => (dagView = "map")}>Map</button
            >
            <button
              class="toggle-btn"
              class:active={dagView === "replay"}
              onclick={() => (dagView = "replay")}>Replay</button
            >
          </div>
          {#if dagView === "map"}
            <MetroDagFull
              {graphJson}
              participants={dagParticipants}
              onzonecodex={openZoneCodex}
            />
          {:else}
            <TrainingReplay
              {graphJson}
              currentPlayer={dagParticipants[0]}
              ghosts={ghostParticipants}
            />
          {/if}
        {:else if (status === "abandoned" || status === "cancelled") && dagParticipants.length > 0}
          <MetroDagFull
            {graphJson}
            participants={dagParticipants}
            onzonecodex={openZoneCodex}
          />
        {:else if status === "active" && dagParticipants.length > 0}
          <div class="dag-toolbar">
            <button
              class="btn btn-secondary btn-sm"
              onclick={() => (showFullDag = !showFullDag)}
            >
              {showFullDag ? "Hide Spoiler" : "Show Spoiler"}
            </button>
            {#if isOwner}
              <button
                class="btn btn-secondary btn-sm"
                onclick={() => (showObsModal = true)}
              >
                OBS Overlay
              </button>
            {/if}
          </div>
          <div class="dag-wrapper">
            {#if showFullDag}
              <MetroDagFull
                {graphJson}
                participants={dagParticipants}
                onzonecodex={openZoneCodex}
              />
            {:else}
              <MetroDagProgressive
                {graphJson}
                participants={dagParticipants}
                myParticipantId={liveParticipant?.id ?? ""}
                onzonecodex={openZoneCodex}
              />
            {/if}
          </div>
        {:else}
          <MetroDag {graphJson} />
        {/if}
      </section>
    {/if}

    {#if session.pool_config}
      <PoolSettingsCard
        poolName={session.pool_config?.name ||
          formatPoolName(session.pool_name)}
        poolConfig={session.pool_config}
      />
    {/if}
  {/if}
</main>

{#if zoneSheetTarget}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="drawer-scrim" onclick={closeZoneSheet}></div>
  <div
    class="drawer"
    role="dialog"
    aria-modal="true"
    aria-label="Zone details"
    tabindex="-1"
    bind:this={drawerEl}
  >
    <ZoneSheet
      nodeId={zoneSheetTarget.nodeId}
      displayName={zoneSheetTarget.displayName}
      zones={zoneSheetTarget.zones}
      onClose={closeZoneSheet}
    />
  </div>
{/if}

{#if showAbandonConfirm}
  <ConfirmModal
    title="Abandon Run"
    message="Abandon this training run? Your current progress will be saved."
    confirmLabel="Abandon"
    danger
    loading={abandoning}
    onConfirm={handleAbandon}
    onCancel={() => (showAbandonConfirm = false)}
  />
{/if}

{#if showObsModal}
  <ObsOverlayModal
    mode="training"
    {sessionId}
    onClose={() => (showObsModal = false)}
  />
{/if}

{#if showFeedback}
  <FeedbackModal source="user_menu" onClose={() => (showFeedback = false)} />
{/if}

{#if showDownloadModal}
  <DownloadModal
    {downloading}
    error={null}
    actionLabel="Download Training Pack"
    rules={session?.pool_config?.rules ?? null}
    tips={starterTips}
    onClose={() => (showDownloadModal = false)}
    onDownload={() => {
      showDownloadModal = false;
      handleDownload();
    }}
  />
{/if}

<style>
  .training-detail {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
    box-sizing: border-box;
  }

  .loading {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .ws-error {
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    min-height: 40vh;
    text-align: center;
    gap: 0.5rem;
  }

  .ws-error h2 {
    color: var(--color-text);
    font-size: 1.5rem;
  }

  .ws-error-detail {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
    padding: 3rem;
    color: var(--color-text-secondary);
  }

  /* Header */
  .header {
    display: flex;
    justify-content: space-between;
    align-items: center;
    margin-bottom: 1.5rem;
  }

  .header-left {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .back-link {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-decoration: none;
  }

  .back-link:hover {
    color: var(--color-purple);
  }

  h1 {
    color: var(--color-gold);
    font-size: var(--font-size-2xl);
    font-weight: 700;
    margin: 0;
  }

  .player-name {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }

  .player-link {
    color: inherit;
    text-decoration: none;
    display: inline-flex;
    align-items: center;
    gap: 0.25rem;
  }

  .player-link:hover {
    color: var(--color-purple);
    text-decoration: underline;
  }

  .player-avatar {
    width: 18px;
    height: 18px;
    border-radius: 50%;
    object-fit: cover;
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

  /* Stats bar */
  .stats-bar {
    display: flex;
    gap: 2rem;
    padding: 1rem 1.5rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    margin-bottom: 1.5rem;
  }

  .stat {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
  }

  .stat-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
  }

  .stat-value {
    font-size: var(--font-size-lg);
    font-weight: 600;
  }

  .mono {
    font-variant-numeric: tabular-nums;
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

  .stat-right {
    margin-left: auto;
  }

  .stat-date {
    font-size: var(--font-size-sm);
    font-weight: 500;
    color: var(--color-text-secondary);
  }

  .connected-dot {
    color: var(--color-success);
    text-align: center;
  }

  /* DAG view toggle */
  .dag-view-toggle {
    display: flex;
    gap: 0.25rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 0.25rem;
    width: fit-content;
    margin-bottom: 0.75rem;
  }

  .toggle-btn {
    all: unset;
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    color: var(--color-text-disabled);
    padding: 0.35rem 0.9rem;
    border-radius: var(--radius-md);
    cursor: pointer;
    transition: all var(--transition);
  }

  .toggle-btn:hover {
    color: var(--color-text-secondary);
  }

  .toggle-btn.active {
    background: var(--color-border);
    color: var(--color-text);
    font-weight: 600;
  }

  /* DAG section */
  .dag-section {
    margin-bottom: 1.5rem;
  }

  .dag-toolbar {
    display: flex;
    gap: 0.5rem;
    align-items: center;
  }

  .dag-wrapper {
    margin-top: 0.75rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
  }

  :global(.training-detail .dag-section svg) {
    min-height: 500px;
  }

  /* Actions */
  .actions {
    display: flex;
    gap: 1rem;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 1rem;
  }

  .tip-banner {
    margin: 0.75rem 0;
  }

  :global(.btn-sm) {
    font-size: var(--font-size-sm);
    padding: 0.35rem 0.75rem;
  }

  /* Zone codex drawer */
  .drawer-scrim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    z-index: 900;
  }

  .drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    height: 100vh;
    width: min(430px, 100%);
    background: var(--color-surface);
    border-left: 1px solid var(--color-border);
    box-shadow: -4px 0 20px rgba(0, 0, 0, 0.4);
    z-index: 901;
    overflow: hidden;
    outline: none;
  }

  @media (max-width: 640px) {
    .training-detail {
      padding: 1rem;
    }

    .stats-bar {
      gap: 1rem;
      flex-wrap: wrap;
    }

    .drawer {
      width: 100%;
    }
  }
</style>
