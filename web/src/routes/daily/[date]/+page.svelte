<script lang="ts">
  import { untrack } from "svelte";
  import { goto } from "$app/navigation";
  import { auth } from "$lib/stores/auth.svelte";
  import { raceStore } from "$lib/stores/race.svelte";
  import { joinableStore } from "$lib/stores/joinable.svelte";
  import { getEffectiveLocale } from "$lib/stores/locale.svelte";
  import {
    computePublicAccess,
    computePublicLockedReason,
  } from "$lib/public-chat-access";
  import {
    abandonRace,
    deleteRace,
    downloadMySeedPack,
    fetchDailyByDate,
    fetchDailyWeek,
    fetchWeeklyLeaderboard,
    getTwitchLoginUrl,
    joinRace,
    type DailyWeekResponse,
    type ParticipantStatus as ApiParticipantStatus,
    type RaceDetail,
    type RaceStatus as ApiRaceStatus,
    type WeeklyLeaderboardResponse,
  } from "$lib/api";
  import {
    applyLiveDailyDayUpdate,
    currentUserParticipant,
    dailyTheme,
    dailyTitle,
  } from "$lib/daily";
  import { MetroDagFull, MetroDagProgressive } from "$lib/dag";
  import { parseDagGraph } from "$lib/dag/types";
  import { RaceReplay } from "$lib/replay";
  import Leaderboard from "$lib/components/Leaderboard.svelte";
  import WeekLeaderboard from "$lib/components/WeekLeaderboard.svelte";
  import SpectatorCount from "$lib/components/SpectatorCount.svelte";
  import RaceControls from "$lib/components/RaceControls.svelte";
  import RaceStats from "$lib/components/RaceStats.svelte";
  import RaceHighlights from "$lib/components/RaceHighlights.svelte";
  import Podium from "$lib/components/Podium.svelte";
  import PoolSettingsCard from "$lib/components/PoolSettingsCard.svelte";
  import ShareButtons from "$lib/components/ShareButtons.svelte";
  import SurveyBanner from "$lib/components/SurveyBanner.svelte";
  import ChatSidebar from "$lib/components/ChatSidebar.svelte";
  import DailyWeekGrid from "$lib/components/DailyWeekGrid.svelte";
  import ConfirmModal from "$lib/components/ConfirmModal.svelte";
  import DownloadModal from "$lib/components/DownloadModal.svelte";
  import FeedbackModal from "$lib/components/FeedbackModal.svelte";

  let { data } = $props();
  let initialRace: RaceDetail = $state(untrack(() => data.race));
  // Set by the daily-boundary refetch; otherwise we read ``data.week``.
  let weekOverride = $state<DailyWeekResponse | null>(null);
  let now = $state(Date.now());
  let showDownloadModal = $state(false);
  let downloading = $state(false);
  let downloadError = $state<string | null>(null);
  let joining = $state(false);
  let joinError = $state<string | null>(null);
  let showAbandonConfirm = $state(false);
  let abandoning = $state(false);
  let abandonError = $state<string | null>(null);
  let chatCollapsed = $state(
    typeof window !== "undefined" ? window.innerWidth < 1600 : true,
  );
  let chatActiveTab = $state<"participants" | "public">("participants");
  let selectedParticipantIds = $state<Set<string>>(new Set());
  let highlightFocusNodeId = $state<string | null>(null);
  let dagView = $state<"map" | "replay">("map");
  let activeLeaderboardTab: "daily" | "week" = $state("daily");
  let weekLeaderboardData: WeeklyLeaderboardResponse | null = $state(null);
  let weekLeaderboardLoading = $state(false);
  let weekLeaderboardError: string | null = $state(null);
  let weekLeaderboardDate: string | null = $state(null);

  async function loadWeekLeaderboardIfNeeded() {
    if (weekLeaderboardData || weekLeaderboardLoading) return;
    if (!initialRace.daily_date) return;
    weekLeaderboardLoading = true;
    weekLeaderboardError = null;
    try {
      weekLeaderboardData = await fetchWeeklyLeaderboard(
        initialRace.daily_date,
      );
      weekLeaderboardDate = initialRace.daily_date;
    } catch (e) {
      weekLeaderboardError = e instanceof Error ? e.message : String(e);
    } finally {
      weekLeaderboardLoading = false;
    }
  }

  $effect(() => {
    if (initialRace.daily_date && initialRace.daily_date !== weekLeaderboardDate) {
      weekLeaderboardData = null;
      weekLeaderboardError = null;
      if (activeLeaderboardTab === "week") {
        void loadWeekLeaderboardIfNeeded();
      }
    }
  });

  function selectLeaderboardTab(tab: "daily" | "week") {
    activeLeaderboardTab = tab;
    if (tab === "week") void loadWeekLeaderboardIfNeeded();
  }

  function handleLeaderboardToggle(id: string, ctrlKey: boolean) {
    if (ctrlKey) {
      const next = new Set(selectedParticipantIds);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      selectedParticipantIds = next;
    } else {
      if (selectedParticipantIds.size === 1 && selectedParticipantIds.has(id)) {
        selectedParticipantIds = new Set();
      } else {
        selectedParticipantIds = new Set([id]);
      }
    }
  }

  function clearSelection() {
    selectedParticipantIds = new Set();
  }

  function handleHighlightZoneClick(nodeId: string) {
    // Reset first so re-clicking the same zone re-triggers the $effect
    highlightFocusNodeId = null;
    requestAnimationFrame(() => {
      highlightFocusNodeId = nodeId;
    });
  }

  $effect(() => {
    initialRace = data.race;
    // Drop the previous daily's refetched override on URL nav.
    weekOverride = null;
  });

  let wsError = $derived(raceStore.wsError);
  let raceStatus = $derived(raceStore.race?.status ?? initialRace.status);
  let kickerLabel = $derived(
    `DAILY · ${new Date(`${initialRace.daily_date}T00:00:00Z`)
      .toLocaleDateString("en-US", {
        weekday: "short",
        month: "short",
        day: "numeric",
        timeZone: "UTC",
      })
      .toUpperCase()}`,
  );
  let raceEndsAt = $derived(
    raceStore.race?.race_ends_at ?? initialRace.race_ends_at,
  );
  let dailyEnded = $derived(
    raceEndsAt
      ? new Date(raceEndsAt).getTime() <= now
      : raceStatus === "finished",
  );
  let myParticipant = $derived(
    currentUserParticipant(initialRace, auth.user?.id),
  );
  let myWsParticipant = $derived(
    raceStore.participants.find((p) => p.id === myParticipant?.id) ?? null,
  );
  let myParticipantStatus = $derived(
    myWsParticipant?.status ?? myParticipant?.status ?? null,
  );
  let myParticipantFinished = $derived(
    myParticipantStatus === "finished" || myParticipantStatus === "abandoned",
  );
  // The daily has no organizer/caster surface, so participants access is
  // purely "do you have a participant row?" plus the admin override.
  let hasParticipantsAccess = $derived(auth.isAdmin || !!myParticipant);
  let isParticipantPlaying = $derived(
    !!myParticipant && raceStatus === "running" && !myParticipantFinished,
  );

  // When the viewer crosses the finish line (or abandons), the public chat
  // becomes the relevant channel for the rest of the daily. Conversely, if a
  // rerolled participant goes back into a playing state, snap them back to
  // the spoiler-free participants tab. Mirrors the race page behavior.
  let prevFinished = $state(false);
  $effect(() => {
    if (myParticipantFinished && !prevFinished) {
      chatActiveTab = "public";
    }
    prevFinished = myParticipantFinished;
  });

  let prevPlaying = $state(false);
  $effect(() => {
    if (isParticipantPlaying && !prevPlaying && chatActiveTab === "public") {
      chatActiveTab = "participants";
    }
    prevPlaying = isParticipantPlaying;
  });

  let showFeedback = $state(false);
  let feedbackShown = $state(false);
  $effect(() => {
    // Read deps unconditionally (see /race/[id]) so Svelte tracks status
    // transitions even after early returns short-circuit a run.
    const ws = myWsParticipant;
    const played =
      ws != null &&
      (ws.status === "finished" ||
        (ws.status === "abandoned" && ws.igt_ms > 0));
    if (showFeedback || feedbackShown) return;
    if (!auth.user) return;
    if (auth.user.feedback_prompted_at) return;
    if (played) {
      feedbackShown = true;
      showFeedback = true;
    }
  });
  let canShowFullDag = $derived(
    dailyEnded ||
      myParticipantStatus === "finished" ||
      myParticipantStatus === "abandoned",
  );
  let canShowProgressiveDag = $derived(
    myParticipantStatus === "registered" ||
      myParticipantStatus === "ready" ||
      myParticipantStatus === "playing",
  );
  let canAbandon = $derived(
    raceStatus === "running" &&
      !!myParticipant &&
      (myParticipantStatus === "playing" ||
        myParticipantStatus === "ready" ||
        myParticipantStatus === "registered"),
  );
  let graphJson = $derived(raceStore.seed?.graph_json ?? null);
  let totalLayers = $derived(
    raceStore.seed?.total_layers ?? initialRace.seed_total_layers ?? 0,
  );
  let seedsReleased = $derived(
    raceStore.race
      ? raceStore.race.seeds_released_at !== null
      : initialRace.seeds_released_at !== null,
  );
  // Build node ID -> display name map so the leaderboard can show competitors'
  // current zones once the viewer has finished or the daily has ended.
  let zoneNames: Map<string, string> | null = $derived.by(() => {
    if (!graphJson) return null;
    const graph = parseDagGraph(graphJson);
    const map = new Map<string, string>();
    for (const node of graph.nodes) {
      map.set(node.id, node.displayName);
    }
    return map;
  });
  let registrationOpenWindow = $derived(
    initialRace.registration_closes_at !== null &&
      initialRace.registration_closes_at !== undefined &&
      new Date(initialRace.registration_closes_at).getTime() > now,
  );
  // Mirrors the race page rule (`dagHiddenByRunningRules` + "I'm still racing"):
  // hide opponents' run details (zone, deaths, weapon loadout) while the
  // late-join window is open so a potential late joiner can't gain
  // positional intel by spectating, and hide them from a participant who
  // hasn't crossed the finish line yet to avoid spoilers. For a standard
  // daily the late-join window spans the full 24h, so non-participants only
  // ever see these details after the daily ends.
  let showRunDetails = $derived(
    canShowFullDag || (!myParticipant && !registrationOpenWindow),
  );
  let countdownLabel = $derived.by(() => {
    if (!raceEndsAt) return "Closes today";
    const totalSeconds = Math.max(
      0,
      Math.floor((new Date(raceEndsAt).getTime() - now) / 1000),
    );
    const hours = Math.floor(totalSeconds / 3600);
    const minutes = Math.floor((totalSeconds % 3600) / 60);
    const seconds = totalSeconds % 60;
    if (hours > 0) return `Closes in ${hours}h ${minutes}m`;
    if (minutes > 0) return `Closes in ${minutes}m ${seconds}s`;
    return `Closes in ${seconds}s`;
  });
  let publicAccessInputs = $derived({
    raceStatus: raceStatus as ApiRaceStatus,
    registrationClosesAt: initialRace.registration_closes_at,
    participantStatus: myParticipantStatus as ApiParticipantStatus | null,
    now: new Date(now),
    isDaily: true,
  });
  let publicAccess = $derived(computePublicAccess(publicAccessInputs));
  let publicLockedReason = $derived(
    computePublicLockedReason(publicAccessInputs),
  );
  let effectiveActiveTab = $derived(
    hasParticipantsAccess ? chatActiveTab : "public",
  );
  let canSendChat = $derived(
    effectiveActiveTab === "participants"
      ? hasParticipantsAccess
      : auth.isLoggedIn && publicAccess === "readable" && !isParticipantPlaying,
  );
  let showChatSidebar = $derived(
    auth.isLoggedIn || publicAccess === "readable",
  );

  // Only the cell matching this page's race can be live-patched (we have
  // no WS subscription for the other days). ``/`` and ``/dashboard`` skip
  // this step entirely and render ``data.week`` directly.
  let weekSource = $derived(weekOverride ?? data.week ?? null);
  let liveWeek = $derived.by(() => {
    if (!weekSource) return null;
    if (!raceStore.race) return weekSource;
    if (!initialRace.daily_date) return weekSource;
    return applyLiveDailyDayUpdate(weekSource, {
      date: initialRace.daily_date,
      participants: raceStore.participants,
      myParticipantId: myParticipant?.id ?? null,
    });
  });
  // Refetch once when the daily window closes while the page is open so
  // the grid's "today" badge moves to the new active day. Seeding
  // ``prevDailyEnded`` from the current value via untrack skips a wasted
  // refetch when the page opens on an already-ended daily.
  let prevDailyEnded = $state(untrack(() => dailyEnded));
  $effect(() => {
    if (dailyEnded && !prevDailyEnded) {
      fetchDailyWeek(initialRace.daily_date ?? undefined)
        .then((w) => {
          weekOverride = w;
        })
        .catch(() => {});
      // Invalidate the cached weekly leaderboard so the Week tab reflects
      // the just-ended daily's final standings on next open.
      weekLeaderboardData = null;
      if (activeLeaderboardTab === "week") void loadWeekLeaderboardIfNeeded();
    }
    prevDailyEnded = dailyEnded;
  });

  // Patch ``my_streak`` in place when the server unicasts a
  // ``daily_streak_update`` (viewer just crossed qualification on this
  // daily, or abandoned and consumed a freeze). ``weekOverride`` is the
  // writable mirror of ``data.week``, so updating it propagates through
  // ``weekSource`` -> ``liveWeek`` and refreshes the streak info rendered
  // inside the ``DailyWeekGrid`` toolbar.
  //
  // When ``freeze_consumed_for`` is set, also flip the matching day's
  // ``freeze_protected`` so the cell strip switches to "❄️ Freeze"
  // immediately. Without this the strip would stay "Abandoned" until the
  // next page load even though the toolbar correctly shows the
  // decremented freeze count.
  //
  // Reads the current source via untrack so this effect only re-runs
  // when a new update arrives.
  $effect(() => {
    const update = raceStore.dailyStreakUpdate;
    if (!update) return;
    const base = untrack(() => weekOverride ?? data.week ?? null);
    if (!base) return;
    const days = update.freeze_consumed_for
      ? base.days.map((d) =>
          d.date === update.freeze_consumed_for
            ? { ...d, freeze_protected: true }
            : d,
        )
      : base.days;
    weekOverride = {
      ...base,
      days,
      my_streak: {
        current: update.current,
        best: update.best,
        freeze_count: update.freeze_count,
      },
    };
  });

  // Pull public chat history when local access transitions from locked to
  // readable (e.g. the viewer's run just transitioned to FINISHED, or
  // registration window closed). The server already shipped history at
  // auth time when we were eligible; this re-pulls only on the lift.
  let prevPublicAccess = $state<"locked" | "readable" | null>(null);
  $effect(() => {
    const current = publicAccess;
    if (prevPublicAccess === "locked" && current === "readable") {
      raceStore.send({ type: "request_chat_history", channel: "public" });
    }
    prevPublicAccess = current;
  });

  $effect(() => {
    if (!auth.initialized) return;
    const locale = untrack(() => getEffectiveLocale());
    raceStore.connect(initialRace.id, locale);
    return () => raceStore.disconnect();
  });

  $effect(() => {
    // Stop ticking once the daily window is closed: the closes-in pill, the
    // dailyEnded predicate, and the late-join guard all freeze at that
    // point, so further ticks just churn $derived recomputes for nothing.
    if (dailyEnded) return;
    const timer = setInterval(() => (now = Date.now()), 1000);
    return () => clearInterval(timer);
  });

  async function handlePlayNow() {
    if (!auth.isLoggedIn) {
      sessionStorage.setItem("redirect_after_login", window.location.pathname);
      goto(getTwitchLoginUrl());
      return;
    }
    joining = true;
    joinError = null;
    try {
      await joinRace(initialRace.id);
      initialRace = await fetchDailyByDate(initialRace.daily_date!);
      raceStore.reconnect();
      joinableStore.invalidate();
      showDownloadModal = true;
    } catch (e) {
      joinError = e instanceof Error ? e.message : "Failed to join";
    } finally {
      joining = false;
    }
  }

  async function handleDownload() {
    downloading = true;
    downloadError = null;
    try {
      await downloadMySeedPack(initialRace.id);
      showDownloadModal = false;
    } catch (e) {
      downloadError = e instanceof Error ? e.message : "Download failed";
    } finally {
      downloading = false;
    }
  }

  async function handleAbandon() {
    abandoning = true;
    abandonError = null;
    try {
      await abandonRace(initialRace.id);
      initialRace = await fetchDailyByDate(initialRace.daily_date!);
      showAbandonConfirm = false;
    } catch (e) {
      abandonError = e instanceof Error ? e.message : "Failed to abandon";
    } finally {
      abandoning = false;
    }
  }

  function sendChatMessage(
    message: string,
    channel: "participants" | "public",
  ) {
    raceStore.send({ type: "chat", channel, message });
  }
</script>

<svelte:head>
  <title>{dailyTitle(initialRace.daily_date!)}</title>
</svelte:head>

{#if wsError}
  <div class="ws-error">
    <h2>
      {#if wsError.code === 4004}
        Daily not found
      {:else if wsError.code === 4003}
        Authentication error
      {:else}
        Connection error
      {/if}
    </h2>
    <p class="ws-error-detail">{wsError.reason}</p>
    <a href="/daily" class="btn btn-primary">Back to dailies</a>
  </div>
{:else}
  <div class="daily-page">
    <aside class="sidebar">
      <div class="sidebar-section">
        <div class="leaderboard-header">
          <h2>Leaderboard</h2>
          <div class="lb-tabs">
            <button
              type="button"
              class="lb-tab"
              class:active={activeLeaderboardTab === "daily"}
              onclick={() => selectLeaderboardTab("daily")}
            >
              Daily
            </button>
            <button
              type="button"
              class="lb-tab"
              class:active={activeLeaderboardTab === "week"}
              onclick={() => selectLeaderboardTab("week")}
            >
              Week
            </button>
          </div>
        </div>

        {#if activeLeaderboardTab === "daily"}
          <Leaderboard
            participants={raceStore.leaderboard}
            {totalLayers}
            mode={dailyEnded ? "finished" : "running"}
            {zoneNames}
            {showRunDetails}
            selectedIds={selectedParticipantIds}
            onToggle={handleLeaderboardToggle}
            onClearSelection={clearSelection}
          />
        {:else if weekLeaderboardLoading}
          <p class="lb-info">Loading...</p>
        {:else if weekLeaderboardError}
          <p class="lb-info">Failed to load: {weekLeaderboardError}</p>
        {:else if weekLeaderboardData}
          <WeekLeaderboard
            data={weekLeaderboardData}
            currentUserId={auth.user?.id ?? null}
          />
        {/if}
      </div>

      {#if canAbandon}
        <div class="abandon-section">
          <button
            class="abandon-btn"
            onclick={() => (showAbandonConfirm = true)}
          >
            Rage quit
          </button>
          {#if abandonError}
            <p class="abandon-error">{abandonError}</p>
          {/if}
        </div>
      {/if}

      {#if myParticipant && seedsReleased}
        <button
          class="sidebar-download-btn"
          onclick={() => {
            downloadError = null;
            showDownloadModal = true;
          }}
          disabled={downloading}
        >
          <svg viewBox="0 0 16 16" width="16" height="16" aria-hidden="true">
            <path
              d="M8 1v9m0 0L5 7m3 3 3-3M3 13h10"
              stroke="currentColor"
              stroke-width="1.5"
              stroke-linecap="round"
              stroke-linejoin="round"
              fill="none"
            />
          </svg>
          {downloading ? "Preparing..." : "Download Daily Seed Pack"}
        </button>
      {/if}

      <SpectatorCount count={raceStore.spectatorCount} />
    </aside>

    <main class="main-content">
      {#if auth.user?.feedback_prompted_at}
        <SurveyBanner />
      {/if}
      <header class="daily-header">
        <div class="daily-title">
          <span class="kicker">{kickerLabel}</span>
          <h1>{dailyTheme(initialRace)}</h1>
        </div>
        <div class="daily-meta-right">
          <ShareButtons />
          {#if initialRace.seed_number}
            <span class="seed-badge">Seed {initialRace.seed_number}</span>
          {/if}
          <span class="daily-pill" class:ended={dailyEnded}>
            {dailyEnded ? "Ended" : countdownLabel}
          </span>
        </div>
      </header>

      {#if liveWeek}
        <DailyWeekGrid
          week={liveWeek}
          variant="daily-detail"
          selectedDate={initialRace.daily_date ?? undefined}
        />
      {/if}

      {#if raceStatus === "finished" && graphJson}
        <Podium participants={raceStore.leaderboard} />
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
      {/if}

      <div class="dag-wrapper">
        {#if !myParticipant && !dailyEnded}
          <button
            class="dag-placeholder play-now-cta"
            onclick={handlePlayNow}
            disabled={joining}
          >
            <span class="play-now-label"
              >{joining ? "Joining..." : "Play now"}</span
            >
            {#if joinError}
              <span class="play-now-error">{joinError}</span>
            {/if}
          </button>
        {:else if graphJson && raceStatus === "finished"}
          {#if dagView === "map"}
            <MetroDagFull
              {graphJson}
              participants={raceStore.leaderboard}
              {raceStatus}
              highlightIds={selectedParticipantIds}
              focusNodeId={highlightFocusNodeId}
            />
          {:else}
            <RaceReplay
              {graphJson}
              participants={raceStore.leaderboard}
              focusNodeId={highlightFocusNodeId}
              highlightIds={selectedParticipantIds}
            />
          {/if}
        {:else if graphJson && canShowFullDag}
          <MetroDagFull
            {graphJson}
            participants={raceStore.leaderboard}
            {raceStatus}
            highlightIds={selectedParticipantIds}
            focusNodeId={highlightFocusNodeId}
          />
        {:else if graphJson && canShowProgressiveDag}
          <MetroDagProgressive
            {graphJson}
            participants={raceStore.participants}
            myParticipantId={myWsParticipant?.id ?? ""}
          />
        {:else}
          <div class="dag-placeholder">
            <p class="dag-note">Loading map...</p>
          </div>
        {/if}
      </div>

      {#if dailyEnded || myParticipantStatus === "finished"}
        <RaceStats participants={raceStore.leaderboard} />
        {#if graphJson}
          <RaceHighlights
            participants={raceStore.leaderboard}
            {graphJson}
            myParticipantId={myWsParticipant?.id}
            onzoneclick={handleHighlightZoneClick}
          />
        {/if}
      {/if}

      {#if auth.isAdmin}
        <RaceControls
          race={initialRace}
          {raceStatus}
          onRaceUpdated={(race) => (initialRace = race)}
          onDeleteRace={async () => {
            await deleteRace(initialRace.id);
            goto("/daily");
          }}
        />
      {/if}

      {#if initialRace.pool_name && initialRace.pool_config}
        <PoolSettingsCard
          poolName={initialRace.pool_name}
          poolConfig={initialRace.pool_config}
        />
      {/if}
    </main>

    {#if showChatSidebar}
      <ChatSidebar
        messagesParticipants={raceStore.chatMessagesParticipants}
        messagesPublic={raceStore.chatMessagesPublic}
        canSend={canSendChat}
        collapsed={chatCollapsed}
        participantsAccess={hasParticipantsAccess}
        {publicAccess}
        {publicLockedReason}
        activeTab={effectiveActiveTab}
        historyVersion={raceStore.chatHistoryVersion}
        onSend={sendChatMessage}
        onToggle={() => (chatCollapsed = !chatCollapsed)}
        onTabChange={(tab) => (chatActiveTab = tab)}
      />
    {/if}
  </div>

  {#if showDownloadModal}
    <DownloadModal
      onClose={() => (showDownloadModal = false)}
      onDownload={handleDownload}
      {downloading}
      error={downloadError}
      actionLabel="Download Daily Seed Pack"
    />
  {/if}

  {#if showAbandonConfirm}
    <ConfirmModal
      title="Rage Quit"
      message="Are you sure? This is irreversible."
      confirmLabel="Rage quit"
      danger
      loading={abandoning}
      onConfirm={handleAbandon}
      onCancel={() => (showAbandonConfirm = false)}
    />
  {/if}

  {#if showFeedback}
    <FeedbackModal
      source="post_first_race"
      raceId={initialRace.id}
      entityKind="daily"
      onClose={() => (showFeedback = false)}
    />
  {/if}
{/if}

<style>
  .dag-view-toggle {
    display: flex;
    gap: 0.25rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 0.25rem;
    width: fit-content;
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

  .daily-page {
    display: flex;
    flex: 1;
    min-height: 0;
  }

  .sidebar {
    width: 280px;
    background: var(--color-surface);
    border-right: 1px solid var(--color-border);
    padding: 1.5rem;
    flex-shrink: 0;
    display: flex;
    flex-direction: column;
    gap: 1rem;
    min-height: 0;
  }

  .sidebar-section {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
    min-height: 0;
  }

  .leaderboard-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 1rem;
  }

  .leaderboard-header h2 {
    color: var(--color-gold);
    font-size: var(--font-size-lg);
    font-weight: 600;
    margin: 0;
  }

  .lb-tabs {
    display: inline-flex;
    gap: 0.15rem;
  }

  .lb-tab {
    appearance: none;
    background: transparent;
    border: 1px solid transparent;
    color: var(--color-text-secondary);
    padding: 0.15rem 0.4rem;
    border-radius: var(--radius-sm);
    cursor: pointer;
    font-family: inherit;
    font-size: var(--font-size-xs, 11px);
  }

  .lb-tab.active {
    color: var(--color-gold);
    background: rgba(200, 164, 78, 0.1);
    border-color: rgba(200, 164, 78, 0.35);
  }

  .lb-info {
    color: var(--color-text-secondary);
    text-align: center;
    padding: 1rem 0.5rem;
  }

  .abandon-section {
    padding-top: 0.75rem;
    border-top: 1px solid var(--color-border);
  }

  /* Intentional departure from flat design charter:
	   skeuomorphic "big red button" for dramatic effect. Mirrors /race/[id]. */
  .abandon-btn {
    width: 100%;
    padding: 0.75rem 1rem;
    border: none;
    border-radius: var(--radius-md);
    background: radial-gradient(
      ellipse at 50% 35%,
      #f87171 0%,
      var(--color-danger-dark, #dc2626) 50%,
      #991b1b 100%
    );
    color: #fff;
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    text-shadow: 0 1px 2px rgba(0, 0, 0, 0.4);
    cursor: pointer;
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.15),
      0 4px 0 #7f1d1d,
      0 5px 8px rgba(0, 0, 0, 0.4),
      0 0 20px rgba(239, 68, 68, 0.3);
    transition: all 0.1s ease;
  }

  .abandon-btn:hover {
    background: radial-gradient(
      ellipse at 50% 35%,
      #fca5a5 0%,
      var(--color-danger, #ef4444) 50%,
      #b91c1c 100%
    );
    box-shadow:
      inset 0 1px 0 rgba(255, 255, 255, 0.2),
      0 4px 0 #7f1d1d,
      0 5px 8px rgba(0, 0, 0, 0.4),
      0 0 28px rgba(239, 68, 68, 0.45);
  }

  .abandon-btn:active {
    background: radial-gradient(
      ellipse at 50% 55%,
      var(--color-danger-dark, #dc2626) 0%,
      #b91c1c 50%,
      #7f1d1d 100%
    );
    transform: translateY(3px);
    box-shadow:
      inset 0 2px 3px rgba(0, 0, 0, 0.3),
      0 1px 0 #7f1d1d,
      0 2px 4px rgba(0, 0, 0, 0.3),
      0 0 15px rgba(239, 68, 68, 0.2);
  }

  .abandon-btn:focus-visible {
    outline: 2px solid var(--color-danger, #ef4444);
    outline-offset: 2px;
  }

  .abandon-error {
    margin: 0.5rem 0 0;
    color: var(--color-danger, #ef4444);
    font-size: var(--font-size-sm);
  }

  .sidebar-download-btn {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.65rem 1rem;
    border: 2px solid var(--color-purple);
    border-radius: var(--radius-sm);
    background: rgba(139, 92, 246, 0.1);
    color: var(--color-purple);
    font-family: var(--font-family);
    font-size: var(--font-size-base);
    font-weight: 500;
    cursor: pointer;
    transition: all var(--transition);
  }

  .sidebar-download-btn:hover:not(:disabled) {
    background: rgba(139, 92, 246, 0.2);
    border-color: var(--color-purple-hover);
    color: var(--color-purple-hover);
  }

  .sidebar-download-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .main-content {
    flex: 1;
    padding: 2rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    overflow-y: auto;
    min-width: 0;
  }

  .daily-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
    gap: 1rem;
    flex-wrap: wrap;
  }

  .daily-title .kicker {
    display: block;
    color: var(--color-gold);
    font-size: var(--font-size-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-bottom: 0.25rem;
  }

  .daily-title h1 {
    margin: 0;
    color: var(--color-text);
    font-size: var(--font-size-2xl);
    font-weight: 600;
  }

  .daily-meta-right {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
  }

  .seed-badge {
    font-family: "JetBrains Mono", "Fira Code", monospace;
    font-size: var(--font-size-xs);
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.2rem 0.5rem;
    color: var(--color-text-secondary);
  }

  .daily-pill {
    padding: 0.25rem 0.6rem;
    border: 1px solid var(--color-success);
    color: var(--color-success);
    border-radius: var(--radius-sm);
    font-size: var(--font-size-sm);
  }

  .daily-pill.ended {
    border-color: var(--color-text-disabled);
    color: var(--color-text-disabled);
  }

  .dag-wrapper {
    position: relative;
  }

  /* Match the race page's DAG sizing: ZoomableSvg ships with a 200px
	   minimum but our layout has the room for 400. Scoped to .daily-page
	   so other surfaces (overlays, dashboards) keep their own defaults. */
  :global(.daily-page .zoomable-container) {
    min-height: 400px;
  }

  :global(.daily-page .zoomable-container svg) {
    min-height: 400px;
  }

  .dag-placeholder {
    background: var(--color-surface);
    border: 2px dashed var(--color-border);
    border-radius: var(--radius-lg);
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 400px;
  }

  .dag-note {
    color: var(--color-text-disabled);
    font-size: 0.85rem;
    font-style: italic;
    margin: 0;
  }

  /* The Play now CTA reuses .dag-placeholder's box but adopts a
	   "button label" type ramp (uppercase, letter-spaced, muted) so it
	   reads differently from the H1, plus a slightly elevated surface
	   so it stands out from the other cards on the page. */
  .play-now-cta {
    flex-direction: column;
    gap: 0.5rem;
    width: 100%;
    text-align: center;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    color: var(--color-text-secondary);
    font-family: inherit;
    font-size: var(--font-size-lg);
    font-weight: 600;
    letter-spacing: 0.18em;
    text-transform: uppercase;
    cursor: pointer;
    transition:
      background var(--transition),
      color var(--transition),
      border-color var(--transition);
  }

  .play-now-cta:hover:not(:disabled) {
    border-color: var(--color-purple);
    color: var(--color-purple-hover);
    background: rgba(139, 92, 246, 0.1);
  }

  .play-now-cta:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }

  .play-now-error {
    font-size: var(--font-size-sm);
    font-weight: 400;
    color: var(--color-danger);
  }

  @media (max-width: 768px) {
    .daily-page {
      flex-direction: column;
      flex: initial;
    }

    .sidebar {
      width: 100%;
      border-right: none;
      border-bottom: 1px solid var(--color-border);
      padding: 1rem;
    }

    .main-content {
      padding: 1rem;
      overflow-y: visible;
    }

    .daily-header {
      flex-direction: column;
      gap: 0.5rem;
    }
  }
</style>
