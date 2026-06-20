<script lang="ts">
  import { untrack } from "svelte";
  import { auth } from "$lib/stores/auth.svelte";
  import { getEffectiveLocale } from "$lib/stores/locale.svelte";
  import { raceStore } from "$lib/stores/race.svelte";
  import Leaderboard from "$lib/components/Leaderboard.svelte";
  import RaceStatus from "$lib/components/RaceStatus.svelte";

  import SpectatorCount from "$lib/components/SpectatorCount.svelte";
  import ParticipantCard from "$lib/components/ParticipantCard.svelte";
  import InviteCard from "$lib/components/InviteCard.svelte";
  import ParticipantSearch from "$lib/components/ParticipantSearch.svelte";
  import CasterList from "$lib/components/CasterList.svelte";
  import WatchLive from "$lib/components/WatchLive.svelte";
  import RaceControls from "$lib/components/RaceControls.svelte";
  import Podium from "$lib/components/Podium.svelte";
  import PoolSettingsCard from "$lib/components/PoolSettingsCard.svelte";
  import RaceStats from "$lib/components/RaceStats.svelte";
  import RaceHighlights from "$lib/components/RaceHighlights.svelte";
  import ShareButtons from "$lib/components/ShareButtons.svelte";
  import AddToCalendar from "$lib/components/AddToCalendar.svelte";
  import ChatSidebar from "$lib/components/ChatSidebar.svelte";
  import type {
    ParticipantStatus as ApiParticipantStatus,
    RaceStatus as ApiRaceStatus,
  } from "$lib/api";
  import {
    computePublicAccess,
    computePublicLockedReason,
  } from "$lib/public-chat-access";
  import { isFrogTitle } from "$lib/format";
  import ObsOverlayModal from "$lib/components/ObsOverlayModal.svelte";
  import DownloadModal from "$lib/components/DownloadModal.svelte";
  import ConfirmModal from "$lib/components/ConfirmModal.svelte";
  import FeedbackModal from "$lib/components/FeedbackModal.svelte";
  import { goto } from "$app/navigation";
  import { deleteRace, getTwitchLoginUrl } from "$lib/api";
  import DateTimePicker from "$lib/components/DateTimePicker.svelte";
  import { MetroDag, MetroDagProgressive, MetroDagFull } from "$lib/dag";
  import { parseDagGraph } from "$lib/dag/types";
  import { RaceReplay } from "$lib/replay";
  import {
    downloadMySeedPack,
    removeParticipant,
    deleteInvite,
    fetchRace,
    updateRace,
    joinRace,
    leaveRace,
    abandonRace,
    type RaceDetail,
  } from "$lib/api";
  import { joinableStore } from "$lib/stores/joinable.svelte";

  let downloading = $state(false);
  let downloadError = $state<string | null>(null);
  let showInviteSearch = $state(false);
  let joining = $state(false);
  let leaving = $state(false);
  let joinLeaveError = $state<string | null>(null);
  let showAbandonConfirm = $state(false);
  let abandoning = $state(false);
  let abandonError = $state<string | null>(null);
  let now = $state(Date.now());
  let editingSchedule = $state(false);
  let scheduleInput = $state("");
  let scheduleError = $state<string | null>(null);
  let scheduleSaving = $state(false);
  let editingLateJoin = $state(false);
  let lateJoinInput = $state<number>(30);
  let lateJoinError = $state<string | null>(null);
  let lateJoinSaving = $state(false);
  let editingDuration = $state(false);
  let durationInput = $state<number>(120);
  let durationError = $state<string | null>(null);
  let durationSaving = $state(false);
  let editingRules = $state(false);
  let rulesInput = $state("");
  let rulesError = $state<string | null>(null);
  let rulesSaving = $state(false);
  let selectedParticipantIds = $state<Set<string>>(new Set());
  let showDownloadModal = $state(false);
  let deleting = $state(false);
  let deleteError = $state<string | null>(null);
  let pendingConfirm = $state<{
    title: string;
    message: string;
    confirmLabel: string;
    danger?: boolean;
    action: () => Promise<void>;
  } | null>(null);
  let highlightFocusNodeId = $state<string | null>(null);
  let dagView = $state<"map" | "replay">("map");
  let chatCollapsed = $state(
    typeof window !== "undefined" ? window.innerWidth < 1600 : true,
  );
  let chatActiveTab = $state<"participants" | "public">("participants");
  function handleHighlightZoneClick(nodeId: string) {
    // Reset first so re-clicking the same zone re-triggers the $effect
    highlightFocusNodeId = null;
    requestAnimationFrame(() => {
      highlightFocusNodeId = nodeId;
    });
  }

  function sendChatMessage(
    message: string,
    channel: "participants" | "public",
  ) {
    raceStore.send({ type: "chat", channel, message });
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

  async function handleDeleteRace() {
    deleting = true;
    deleteError = null;
    try {
      await deleteRace(initialRace.id);
      goto("/");
    } catch (e) {
      deleteError = e instanceof Error ? e.message : "Failed to delete race";
      deleting = false;
    }
  }

  let { data } = $props();

  // untrack: initial snapshot only; the $effect below handles route-change updates
  let initialRace: RaceDetail = $state(untrack(() => data.race));

  // Update initialRace when route data changes (navigation between races)
  $effect(() => {
    initialRace = data.race;
    // The selection holds participant IDs from the previous race; a different
    // race has different participants, so clear it to avoid a stale
    // "N selected" pill and phantom DAG highlights.
    selectedParticipantIds = new Set();
  });

  // Live data from WebSocket
  let wsError = $derived(raceStore.wsError);
  let liveRace = $derived(raceStore.race);
  let liveSeed = $derived(raceStore.seed);

  let spectatorCount = $derived(raceStore.spectatorCount);

  // Use live data if available, otherwise fall back to initial
  let raceName = $derived(liveRace?.name ?? initialRace.name);
  let isFrogRace = $derived(isFrogTitle(raceName));
  let raceStatus = $derived(liveRace?.status ?? initialRace.status);
  let liveCustomRules = $derived(
    raceStore.race
      ? (raceStore.race.custom_rules ?? null)
      : (initialRace.custom_rules ?? null),
  );
  let customRuleLines = $derived(
    (liveCustomRules ?? "")
      .split("\n")
      .map((l) => l.trim())
      .filter((l) => l.length > 0),
  );
  let canEditRules = $derived(
    raceStatus === "setup" || raceStatus === "running",
  );
  let totalLayers = $derived(
    liveSeed?.total_layers ?? initialRace.seed_total_layers,
  );
  let seedsReleased = $derived(
    liveRace
      ? liveRace.seeds_released_at !== null
      : initialRace.seeds_released_at !== null,
  );

  // Build node ID → display name map for leaderboard zone labels
  let zoneNames: Map<string, string> | null = $derived.by(() => {
    if (!liveSeed?.graph_json) return null;
    const graph = parseDagGraph(liveSeed.graph_json);
    const map = new Map<string, string>();
    for (const node of graph.nodes) {
      map.set(node.id, node.displayName);
    }
    return map;
  });

  // Merge REST participants with WS live status
  let mergedParticipants = $derived.by(() => {
    const wsMap = new Map(
      raceStore.participants.map((wp) => [wp.twitch_username, wp]),
    );
    return initialRace.participants.map((p) => {
      const ws = wsMap.get(p.user.twitch_username);
      return {
        ...p,
        liveStatus: ws?.status,
        isLive: ws?.is_live ?? false,
        streamUrl: ws?.stream_url ?? null,
      };
    });
  });

  $effect(() => {
    if (!auth.initialized) return;

    const raceId = data.race.id;
    const locale = untrack(() => getEffectiveLocale());
    raceStore.connect(raceId, locale);

    return () => {
      raceStore.disconnect();
    };
  });

  // Re-fetch initialRace when WS delivers a different participant set
  // (e.g., someone joins/leaves while we're viewing the setup page).
  $effect(() => {
    const wsParticipants = raceStore.participants;
    if (wsParticipants.length === 0) return;

    const wsIds = new Set(wsParticipants.map((p) => p.id));
    const restIds = untrack(
      () => new Set(initialRace.participants.map((p) => p.id)),
    );

    if (
      wsIds.size === restIds.size &&
      [...wsIds].every((id) => restIds.has(id))
    )
      return;

    const raceId = untrack(() => initialRace.id);
    fetchRace(raceId).then((r) => (initialRace = r));
  });

  // Wall-clock elapsed timer based on server's started_at timestamp.
  // started_at is the effective gameplay start (server already shifted it
  // by countdown_seconds), so no extra subtraction is needed.
  let startedAt = $derived(liveRace?.started_at ?? initialRace.started_at);

  let elapsedSeconds = $derived.by(() => {
    if (raceStatus !== "running" || !startedAt) return 0;
    const raw = Math.floor((now - new Date(startedAt).getTime()) / 1000);
    return Math.max(0, raw);
  });

  $effect(() => {
    if (raceStatus !== "running" || !startedAt) return;

    const interval = setInterval(() => {
      now = Date.now();
    }, 1000);

    return () => clearInterval(interval);
  });

  let countdownRemaining = $state<number | null>(null);
  let showGo = $state(false);
  let previousRaceStatus: string | null = null;

  $effect(() => {
    const wasNotRunning =
      previousRaceStatus !== null && previousRaceStatus !== "running";
    previousRaceStatus = raceStatus;
    clearSelection();
    if (raceStatus === "running" && wasNotRunning) {
      const cd = untrack(() => liveRace?.countdown_seconds ?? 0);
      if (cd > 0) {
        // Start countdown
        countdownRemaining = cd;
        const interval = setInterval(() => {
          if (countdownRemaining !== null && countdownRemaining > 1) {
            countdownRemaining = countdownRemaining - 1;
          } else {
            clearInterval(interval);
            countdownRemaining = null;
            showGo = true;
            setTimeout(() => {
              showGo = false;
            }, 3000);
          }
        }, 1000);
        return () => {
          clearInterval(interval);
          countdownRemaining = null;
          showGo = false;
        };
      } else {
        // No countdown, show GO! immediately
        countdownRemaining = null;
        showGo = true;
        const timer = setTimeout(() => {
          showGo = false;
        }, 3000);
        return () => clearTimeout(timer);
      }
    } else {
      countdownRemaining = null;
      showGo = false;
    }
  });

  function formatElapsed(totalSeconds: number): string {
    const h = Math.floor(totalSeconds / 3600);
    const m = Math.floor((totalSeconds % 3600) / 60);
    const s = totalSeconds % 60;
    return `${h.toString().padStart(2, "0")}:${m.toString().padStart(2, "0")}:${s.toString().padStart(2, "0")}`;
  }

  let isOrganizer = $derived(auth.user?.id === initialRace.organizer.id);
  let isCaster = $derived(
    auth.user
      ? initialRace.casters.some((c) => c.user.id === auth.user?.id)
      : false,
  );
  let showObsModal = $state(false);

  let myParticipant = $derived(
    auth.user
      ? initialRace.participants.find((p) => p.user.id === auth.user?.id)
      : undefined,
  );

  let myWsParticipant = $derived.by(() => {
    if (!myParticipant) return null;
    return (
      raceStore.participants.find(
        (p) => p.twitch_username === myParticipant.user.twitch_username,
      ) ?? null
    );
  });

  let myWsParticipantId = $derived(myWsParticipant?.id ?? null);
  let myParticipantFinished = $derived(
    myWsParticipant?.status === "finished" ||
      myWsParticipant?.status === "abandoned",
  );

  let hasParticipantsAccess = $derived(
    isOrganizer || auth.isAdmin || isCaster || !!myParticipant,
  );
  let isParticipantPlaying = $derived(
    !!myParticipant && raceStatus === "running" && !myParticipantFinished,
  );

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
    // Read myWsParticipant + status + igt_ms unconditionally so Svelte
    // tracks them as effect dependencies on every run. With early returns
    // before the reads, a short-circuited run registered only the upstream
    // deps, and later status changes never re-triggered the effect.
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

  // Debug: force full DAG view even as participant (call __debugDagFull() in console)
  let forceFullDag = $state(false);
  if (typeof window !== "undefined") {
    (window as any).__debugDagFull = (on?: boolean) => {
      forceFullDag = on ?? !forceFullDag;
      return forceFullDag ? "Full map enabled" : "Progressive map restored";
    };
  }

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleString();
  }

  async function handleParticipantAdded() {
    showInviteSearch = false;
    initialRace = await fetchRace(initialRace.id);
  }

  function handleRemoveParticipant(participantId: string, username: string) {
    pendingConfirm = {
      title: "Remove Participant",
      message: `Remove ${username} from this race?`,
      confirmLabel: "Remove",
      danger: true,
      async action() {
        try {
          await removeParticipant(initialRace.id, participantId);
          initialRace = await fetchRace(initialRace.id);
        } catch (e) {
          console.error("Failed to remove participant:", e);
        }
      },
    };
  }

  function handleRevokeInvite(inviteId: string, username: string) {
    pendingConfirm = {
      title: "Revoke Invite",
      message: `Revoke invite for ${username}?`,
      confirmLabel: "Revoke",
      danger: true,
      async action() {
        try {
          await deleteInvite(initialRace.id, inviteId);
          initialRace = await fetchRace(initialRace.id);
        } catch (e) {
          console.error("Failed to revoke invite:", e);
        }
      },
    };
  }

  let isCasterOrOrganizer = $derived(isCaster || isOrganizer);

  // Live values: prefer the WS-broadcast race when present (raceStore.race
  // is updated by race_state on connect and race_info_update on PATCH) so
  // the UI reflects an organizer's mid-race edit without requiring reload.
  // Fall back to the initial REST fetch when the WS hasn't delivered yet.
  let liveRegistrationClosesAt = $derived(
    raceStore.race?.registration_closes_at ??
      initialRace.registration_closes_at,
  );

  let myParticipantStatus = $derived(
    (myWsParticipant?.status as ApiParticipantStatus | undefined) ?? null,
  );
  let publicAccessInputs = $derived({
    raceStatus: raceStatus as ApiRaceStatus,
    registrationClosesAt: liveRegistrationClosesAt,
    participantStatus: myParticipantStatus,
    now: new Date(now),
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

  // Pull public chat history when local access transitions from locked
  // to readable (late-join window expired, viewer just finished). The
  // server revalidates and silently ignores if the transition is wrong.
  // Skip the very first computation: on initial connection the server
  // already shipped history if we were eligible at auth time.
  let prevPublicAccess = $state<"locked" | "readable" | null>(null);
  $effect(() => {
    const current = publicAccess;
    if (prevPublicAccess === "locked" && current === "readable") {
      raceStore.send({ type: "request_chat_history", channel: "public" });
    }
    prevPublicAccess = current;
  });

  let liveRaceEndsAt = $derived(
    raceStore.race?.race_ends_at ?? initialRace.race_ends_at,
  );
  let livePrivateDag = $derived(
    raceStore.race?.private_dag ?? initialRace.private_dag,
  );
  let liveOpenRegistration = $derived(
    raceStore.race?.open_registration ?? initialRace.open_registration,
  );
  let liveMaxParticipants = $derived(
    raceStore.race?.max_participants ?? initialRace.max_participants,
  );
  // null is a meaningful value for these three (= "disabled" / "to be defined"),
  // so gate on raceStore.race's presence rather than using ?? which would fall
  // back to initialRace when the WS pushes an explicit null.
  let liveLateJoinWindow = $derived(
    raceStore.race
      ? (raceStore.race.late_join_window_minutes ?? null)
      : initialRace.late_join_window_minutes,
  );
  let liveRaceDuration = $derived(
    raceStore.race
      ? (raceStore.race.race_duration_minutes ?? null)
      : initialRace.race_duration_minutes,
  );
  let liveScheduledAt = $derived(
    raceStore.race
      ? (raceStore.race.scheduled_at ?? null)
      : initialRace.scheduled_at,
  );

  // Pending invites: use the WS list (drops accepted/revoked entries live)
  // for presence, enriched from initialRace to keep the organizer's invite
  // token for the copy-link button. WS-only entries render without a token;
  // reloading is enough to get it back.
  let livePendingInvites = $derived.by(() => {
    if (raceStore.pendingInvites === null) {
      return initialRace.pending_invites;
    }
    const tokenById = new Map(
      initialRace.pending_invites.map((p) => [p.id, p.token]),
    );
    return raceStore.pendingInvites.map((p) => ({
      id: p.id,
      twitch_username: p.twitch_username,
      created_at: p.created_at,
      token: tokenById.get(p.id) ?? null,
    }));
  });

  let canJoin = $derived(
    liveOpenRegistration &&
      raceStatus === "setup" &&
      auth.isLoggedIn &&
      !myParticipant &&
      !isCaster &&
      !isOrganizer &&
      (liveMaxParticipants === null ||
        liveMaxParticipants === undefined ||
        mergedParticipants.length < liveMaxParticipants),
  );

  let registrationOpenWindow = $derived(
    liveRegistrationClosesAt !== null &&
      liveRegistrationClosesAt !== undefined &&
      new Date(liveRegistrationClosesAt).getTime() > now,
  );

  let canRejoin = $derived(
    liveOpenRegistration &&
      raceStatus === "running" &&
      auth.isLoggedIn &&
      !myParticipant &&
      !isCasterOrOrganizer &&
      registrationOpenWindow &&
      (liveMaxParticipants === null ||
        liveMaxParticipants === undefined ||
        mergedParticipants.length < liveMaxParticipants),
  );

  let dagHiddenByRunningRules = $derived(
    raceStatus === "running" &&
      !myParticipant &&
      !isCasterOrOrganizer &&
      (livePrivateDag || registrationOpenWindow),
  );

  // Spoiler gate for in-race competitor info (current zone, deaths, weapon
  // loadout). Hidden when I'm still racing (so the leaderboard does not leak
  // others' progress to me) or when the late-join / private-DAG rules apply
  // to a spectator. The forceFullDag toggle and the finished state both
  // re-open visibility.
  let showRunDetails = $derived(
    !(
      raceStatus === "running" &&
      myWsParticipantId &&
      !myParticipantFinished &&
      !forceFullDag
    ) && !dagHiddenByRunningRules,
  );

  let canRenderDag = $derived(
    !!liveSeed?.graph_json &&
      (raceStatus === "running" ||
        raceStatus === "finished" ||
        !!myWsParticipantId ||
        isOrganizer ||
        forceFullDag),
  );

  let dagHidden = $derived(
    dagHiddenByRunningRules || (!canRenderDag && !!totalLayers),
  );

  let dagHiddenReason = $derived.by(() => {
    if (livePrivateDag) return "The map is hidden until the race finishes.";
    if (registrationOpenWindow)
      return "The map is hidden while registration is open.";
    return "Map revealed at race start.";
  });

  function formatLocalTime(iso: string): string {
    const d = new Date(iso);
    return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  }

  function formatCountdown(iso: string, refMs: number): string {
    const diff = Math.max(
      0,
      Math.floor((new Date(iso).getTime() - refMs) / 1000),
    );
    const h = Math.floor(diff / 3600);
    const m = Math.floor((diff % 3600) / 60);
    const s = diff % 60;
    if (h > 0) return `${h}h ${m}min`;
    if (m > 0) return `${m}min ${s}s`;
    return `${s}s`;
  }

  function formatMinutes(minutes: number): string {
    if (minutes <= 60) return `${minutes} min`;
    const h = Math.floor(minutes / 60);
    const m = minutes % 60;
    return m === 0 ? `${h}h` : `${h}h${m}m`;
  }

  let raceFull = $derived(
    liveOpenRegistration &&
      liveMaxParticipants !== null &&
      liveMaxParticipants !== undefined &&
      mergedParticipants.length >= liveMaxParticipants,
  );

  let canLeave = $derived(
    raceStatus === "setup" && !!myParticipant && !isOrganizer,
  );
  let myLiveStatus = $derived(myWsParticipant?.status ?? myParticipant?.status);
  let canAbandon = $derived(
    raceStatus === "running" &&
      !!myParticipant &&
      (myLiveStatus === "playing" ||
        myLiveStatus === "ready" ||
        myLiveStatus === "registered"),
  );

  async function handleJoin() {
    joining = true;
    joinLeaveError = null;
    try {
      await joinRace(initialRace.id);
      initialRace = await fetchRace(initialRace.id);
      raceStore.reconnect();
      joinableStore.invalidate();
    } catch (e) {
      joinLeaveError = e instanceof Error ? e.message : "Failed to join";
    } finally {
      joining = false;
    }
  }

  async function handleLeave() {
    leaving = true;
    joinLeaveError = null;
    try {
      await leaveRace(initialRace.id);
      initialRace = await fetchRace(initialRace.id);
      raceStore.reconnect();
      joinableStore.invalidate();
    } catch (e) {
      joinLeaveError = e instanceof Error ? e.message : "Failed to leave";
    } finally {
      leaving = false;
    }
  }

  async function handleAbandon() {
    abandoning = true;
    abandonError = null;
    try {
      await abandonRace(initialRace.id);
      initialRace = await fetchRace(initialRace.id);
      showAbandonConfirm = false;
    } catch (e) {
      abandonError = e instanceof Error ? e.message : "Failed to abandon";
    } finally {
      abandoning = false;
    }
  }

  function startEditSchedule() {
    scheduleInput = liveScheduledAt ?? "";
    scheduleError = null;
    editingSchedule = true;
  }

  async function saveSchedule() {
    scheduleSaving = true;
    scheduleError = null;
    try {
      const scheduled = scheduleInput || null;
      await updateRace(initialRace.id, { scheduled_at: scheduled });
      initialRace = await fetchRace(initialRace.id);
      editingSchedule = false;
    } catch (e) {
      scheduleError = e instanceof Error ? e.message : "Failed to update";
    } finally {
      scheduleSaving = false;
    }
  }

  function startEditLateJoin() {
    lateJoinInput = liveLateJoinWindow ?? 30;
    lateJoinError = null;
    editingLateJoin = true;
  }

  async function saveLateJoin(value: number | null) {
    lateJoinSaving = true;
    lateJoinError = null;
    try {
      await updateRace(initialRace.id, { late_join_window_minutes: value });
      initialRace = await fetchRace(initialRace.id);
      editingLateJoin = false;
    } catch (e) {
      lateJoinError = e instanceof Error ? e.message : "Failed to update";
    } finally {
      lateJoinSaving = false;
    }
  }

  function startEditDuration() {
    durationInput = liveRaceDuration ?? 120;
    durationError = null;
    editingDuration = true;
  }

  async function saveDuration(value: number | null) {
    durationSaving = true;
    durationError = null;
    try {
      await updateRace(initialRace.id, { race_duration_minutes: value });
      initialRace = await fetchRace(initialRace.id);
      editingDuration = false;
    } catch (e) {
      durationError = e instanceof Error ? e.message : "Failed to update";
    } finally {
      durationSaving = false;
    }
  }

  function startEditRules() {
    rulesInput = liveCustomRules ?? "";
    rulesError = null;
    editingRules = true;
  }

  async function saveRules() {
    rulesSaving = true;
    rulesError = null;
    try {
      await updateRace(initialRace.id, {
        custom_rules: rulesInput.trim() || null,
      });
      initialRace = await fetchRace(initialRace.id);
      editingRules = false;
    } catch (e) {
      rulesError = e instanceof Error ? e.message : "Failed to update";
    } finally {
      rulesSaving = false;
    }
  }

  function handleRaceUpdated(updated: RaceDetail) {
    initialRace = updated;
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
</script>

<svelte:head>
  <title>{raceName} - SpeedFog Racing</title>
  <meta name="robots" content="noindex" />
</svelte:head>

{#if wsError}
  <div class="ws-error">
    <h2>
      {#if wsError.code === 4004}
        Race not found
      {:else if wsError.code === 4003}
        Authentication error
      {:else}
        Connection error
      {/if}
    </h2>
    <p class="ws-error-detail">{wsError.reason}</p>
    <a href="/" class="btn btn-primary">Back to races</a>
  </div>
{:else}
  <div class="race-page">
    <aside class="sidebar">
      {#if raceStatus === "running"}
        <WatchLive casters={initialRace.casters.filter((c) => c.is_live)} />
      {/if}

      {#if raceStatus === "running" || raceStatus === "finished"}
        <div class="sidebar-section">
          <div class="leaderboard-header">
            <h2>{raceStatus === "finished" ? "Results" : "Leaderboard"}</h2>
          </div>
          <Leaderboard
            participants={raceStore.leaderboard}
            {totalLayers}
            mode={raceStatus === "finished" ? "finished" : "running"}
            {zoneNames}
            {showRunDetails}
            selectedIds={selectedParticipantIds}
            onToggle={handleLeaderboardToggle}
            onClearSelection={clearSelection}
          />
        </div>
      {/if}

      {#if raceStatus === "setup"}
        <div class="sidebar-section">
          <h2>
            Participants ({mergedParticipants.length}{#if liveOpenRegistration && liveMaxParticipants}
              /{liveMaxParticipants}{/if})
          </h2>
          <div class="participant-list">
            {#each mergedParticipants as mp (mp.id)}
              <ParticipantCard
                participant={mp}
                liveStatus={mp.liveStatus}
                isOrganizer={mp.user.id === initialRace.organizer.id}
                isCurrentUser={auth.user?.id === mp.user.id}
                isLive={mp.isLive}
                streamUrl={mp.streamUrl}
                canRemove={isOrganizer &&
                  mp.user.id !== initialRace.organizer.id}
                onRemove={() =>
                  handleRemoveParticipant(mp.id, mp.user.twitch_username)}
              />
            {/each}

            {#if livePendingInvites.length > 0}
              {#each livePendingInvites as invite (invite.id)}
                <InviteCard
                  {invite}
                  canRemove={isOrganizer}
                  onRemove={() =>
                    handleRevokeInvite(invite.id, invite.twitch_username)}
                />
              {/each}
            {/if}
          </div>
        </div>
      {/if}

      {#if raceStatus === "running" && registrationOpenWindow && livePendingInvites.length > 0}
        <div class="participant-list">
          {#each livePendingInvites as invite (invite.id)}
            <!-- canRemove=false: backend revoke_invite rejects anything other than SETUP. -->
            <InviteCard {invite} canRemove={false} onRemove={() => {}} />
          {/each}
        </div>
      {/if}

      {#if canJoin || canRejoin}
        <button class="join-btn" onclick={handleJoin} disabled={joining}>
          {joining ? "Joining..." : "Join Race"}
        </button>
      {:else if raceFull && !myParticipant && (raceStatus === "setup" || (raceStatus === "running" && registrationOpenWindow && !isCasterOrOrganizer))}
        <button class="join-btn disabled" disabled> Race Full </button>
      {/if}

      {#if canLeave}
        <button class="leave-btn" onclick={handleLeave} disabled={leaving}>
          {leaving ? "Leaving..." : "Leave Race"}
        </button>
      {/if}

      {#if isOrganizer && (raceStatus === "setup" || (raceStatus === "running" && registrationOpenWindow))}
        {#if showInviteSearch}
          <div class="invite-search">
            <ParticipantSearch
              mode="participant"
              raceId={initialRace.id}
              onAdded={handleParticipantAdded}
              onCancel={() => (showInviteSearch = false)}
            />
          </div>
        {:else}
          <button class="invite-btn" onclick={() => (showInviteSearch = true)}
            >+ Invite</button
          >
        {/if}
      {/if}

      {#if liveRegistrationClosesAt && liveOpenRegistration && (raceStatus === "setup" || (raceStatus === "running" && registrationOpenWindow))}
        <p class="login-hint">
          Joinable until {formatLocalTime(liveRegistrationClosesAt)}
        </p>
      {/if}

      {#if !auth.isLoggedIn && (raceStatus === "setup" || (raceStatus === "running" && registrationOpenWindow))}
        <p class="login-hint">
          <a
            href={getTwitchLoginUrl()}
            data-sveltekit-reload
            onclick={() =>
              sessionStorage.setItem(
                "redirect_after_login",
                window.location.pathname,
              )}>Log in</a
          > to join this race
        </p>
      {/if}

      {#if joinLeaveError}
        <p class="join-leave-error">{joinLeaveError}</p>
      {/if}

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

      {#if myParticipant && (raceStatus === "setup" || raceStatus === "running")}
        {#if seedsReleased}
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
            {downloading ? "Preparing..." : "Download Race Package"}
          </button>
        {:else if raceStatus === "setup"}
          <p class="waiting-seeds">Waiting for seeds...</p>
        {/if}
      {/if}

      {#if raceStatus !== "running"}
        <CasterList
          casters={initialRace.casters}
          editable={raceStatus === "setup" && isOrganizer}
          canCast={raceStatus === "setup" &&
            auth.isLoggedIn &&
            !myParticipant &&
            !isCaster}
          {isCaster}
          currentUserId={auth.user?.id ?? null}
          raceId={initialRace.id}
          onRaceUpdated={handleRaceUpdated}
        />
      {/if}

      {#if raceStatus === "setup" && (isOrganizer || auth.isAdmin || isCaster || myParticipant)}
        <button class="obs-overlay-btn" onclick={() => (showObsModal = true)}
          >OBS Overlays</button
        >
      {/if}

      <div class="sidebar-footer">
        <SpectatorCount count={spectatorCount} />
      </div>
    </aside>

    <main class="main-content">
      <header class="race-header">
        <div>
          <h1 class:frog={isFrogRace}>
            {#if isFrogRace}
              <img src="/badges/frog.svg" alt="" class="frog-icon" />
            {/if}{raceName}
          </h1>
          <p class="organizer">
            Organized by {initialRace.organizer.twitch_display_name ||
              initialRace.organizer.twitch_username}
          </p>
        </div>
        <div class="header-right">
          <ShareButtons />
          {#if initialRace.scheduled_at}
            <AddToCalendar
              scheduledAt={initialRace.scheduled_at}
              {raceName}
              raceUrl={window.location.href}
            />
          {/if}
          {#if !initialRace.is_public}
            <span class="visibility-badge">Private</span>
          {/if}
          {#if initialRace.seed_number}
            <span class="seed-badge">Seed {initialRace.seed_number}</span>
          {/if}
          {#if liveRaceEndsAt && raceStatus === "running"}
            <span class="race-ends-pill">
              Ends in {formatCountdown(liveRaceEndsAt, now)}
            </span>
          {/if}
          <RaceStatus status={raceStatus} />
          {#if raceStatus === "running"}
            <span class="elapsed-clock">{formatElapsed(elapsedSeconds)}</span>
          {/if}
        </div>
      </header>

      {#if liveSeed?.graph_json && raceStatus === "finished"}
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
        {#if countdownRemaining !== null}
          <div class="go-overlay countdown-overlay">
            <span class="countdown-text">{countdownRemaining}</span>
          </div>
        {:else if showGo}
          <div class="go-overlay">
            <span class="go-text">GO!</span>
          </div>
        {/if}

        {#if dagHidden}
          <div class="dag-placeholder">
            <p class="dag-note">{dagHiddenReason}</p>
          </div>
        {:else if liveSeed?.graph_json && raceStatus === "running"}
          {#if myWsParticipantId && !myParticipantFinished && !forceFullDag}
            <MetroDagProgressive
              graphJson={liveSeed.graph_json}
              participants={raceStore.participants}
              myParticipantId={myWsParticipantId}
            />
          {:else}
            <MetroDagFull
              graphJson={liveSeed.graph_json}
              participants={raceStore.leaderboard}
              {raceStatus}
              highlightIds={selectedParticipantIds}
            />
          {/if}
        {:else if liveSeed?.graph_json && raceStatus === "finished"}
          {#if dagView === "map"}
            <MetroDagFull
              graphJson={liveSeed.graph_json}
              participants={raceStore.leaderboard}
              {raceStatus}
              highlightIds={selectedParticipantIds}
              focusNodeId={highlightFocusNodeId}
            />
          {:else}
            <RaceReplay
              graphJson={liveSeed.graph_json}
              participants={raceStore.leaderboard}
              focusNodeId={highlightFocusNodeId}
              highlightIds={selectedParticipantIds}
            />
          {/if}
        {:else if liveSeed?.graph_json && myWsParticipantId && !forceFullDag}
          <MetroDagProgressive
            graphJson={liveSeed.graph_json}
            participants={raceStore.participants}
            myParticipantId={myWsParticipantId}
          />
        {:else if liveSeed?.graph_json && (isOrganizer || forceFullDag)}
          <MetroDag graphJson={liveSeed.graph_json} />
        {/if}
      </div>

      {#if isOrganizer || auth.isAdmin}
        <RaceControls
          race={initialRace}
          {raceStatus}
          onRaceUpdated={handleRaceUpdated}
          onDeleteRace={handleDeleteRace}
        />
      {/if}

      {#if liveSeed?.graph_json && raceStatus === "finished"}
        <RaceStats participants={raceStore.leaderboard} />
        <RaceHighlights
          participants={raceStore.leaderboard}
          graphJson={liveSeed.graph_json}
          myParticipantId={myWsParticipant?.id}
          onzoneclick={handleHighlightZoneClick}
        />
      {/if}

      <div class="race-info">
        <div class="info-grid">
          <div class="info-item">
            <span class="label">Participants</span>
            <span class="value"
              >{mergedParticipants.length}{#if liveOpenRegistration && liveMaxParticipants && (raceStatus === "setup" || (raceStatus === "running" && registrationOpenWindow))}
                /{liveMaxParticipants}{/if}</span
            >
          </div>
          <div class="info-item">
            <span class="label">Created</span>
            <span class="value">{formatDate(initialRace.created_at)}</span>
          </div>
          {#if raceStatus === "setup"}
            <div class="info-item">
              <span class="label">Scheduled</span>
              {#if editingSchedule}
                <div class="schedule-edit">
                  <DateTimePicker
                    value={scheduleInput}
                    onchange={(iso) => (scheduleInput = iso)}
                    min={new Date()}
                    disabled={scheduleSaving}
                  />
                  <div class="schedule-edit-actions">
                    <button
                      class="btn-inline"
                      onclick={saveSchedule}
                      disabled={scheduleSaving}
                    >
                      {scheduleSaving ? "..." : "Save"}
                    </button>
                    <button
                      class="btn-inline btn-inline-secondary"
                      onclick={() => (editingSchedule = false)}
                      disabled={scheduleSaving}
                    >
                      Cancel
                    </button>
                  </div>
                  {#if scheduleError}
                    <span class="schedule-error">{scheduleError}</span>
                  {/if}
                </div>
              {:else if liveScheduledAt}
                <span class="value">
                  {formatDate(liveScheduledAt)}
                  {#if isOrganizer}
                    <button class="btn-edit" onclick={startEditSchedule}
                      >Edit</button
                    >
                  {/if}
                </span>
              {:else if isOrganizer}
                <span class="value">
                  To be defined
                  <button class="btn-edit" onclick={startEditSchedule}
                    >Set time</button
                  >
                </span>
              {:else}
                <span class="value">To be defined</span>
              {/if}
            </div>
            {#if isOrganizer || liveLateJoinWindow !== null}
              <div class="info-item">
                <span class="label">Late join</span>
                {#if editingLateJoin}
                  <div class="schedule-edit">
                    <div class="inline-minutes">
                      <input
                        type="number"
                        min="1"
                        max={liveRaceDuration ?? undefined}
                        bind:value={lateJoinInput}
                        disabled={lateJoinSaving}
                        aria-label="Late join window in minutes"
                        class="inline-duration"
                      />
                      <span>min</span>
                    </div>
                    <div class="schedule-edit-actions">
                      <button
                        class="btn-inline"
                        onclick={() => saveLateJoin(lateJoinInput)}
                        disabled={lateJoinSaving}
                      >
                        {lateJoinSaving ? "..." : "Save"}
                      </button>
                      <button
                        class="btn-inline btn-inline-secondary"
                        onclick={() => (editingLateJoin = false)}
                        disabled={lateJoinSaving}
                      >
                        Cancel
                      </button>
                      {#if liveLateJoinWindow !== null}
                        <button
                          class="btn-inline btn-inline-secondary"
                          onclick={() => saveLateJoin(null)}
                          disabled={lateJoinSaving}
                        >
                          Disable
                        </button>
                      {/if}
                    </div>
                    {#if lateJoinError}
                      <span class="schedule-error">{lateJoinError}</span>
                    {/if}
                  </div>
                {:else if liveLateJoinWindow !== null}
                  <span class="value">
                    {formatMinutes(liveLateJoinWindow)}
                    {#if isOrganizer}
                      <button class="btn-edit" onclick={startEditLateJoin}
                        >Edit</button
                      >
                    {/if}
                  </span>
                {:else}
                  <span class="value">
                    Disabled
                    <button class="btn-edit" onclick={startEditLateJoin}
                      >Enable</button
                    >
                  </span>
                {/if}
              </div>
            {/if}
            {#if isOrganizer || liveRaceDuration !== null}
              <div class="info-item">
                <span class="label">Duration</span>
                {#if editingDuration}
                  <div class="schedule-edit">
                    <div class="inline-minutes">
                      <input
                        type="number"
                        min={liveLateJoinWindow ?? 1}
                        bind:value={durationInput}
                        disabled={durationSaving}
                        aria-label="Race duration in minutes"
                        class="inline-duration"
                      />
                      <span>min</span>
                    </div>
                    <div class="schedule-edit-actions">
                      <button
                        class="btn-inline"
                        onclick={() => saveDuration(durationInput)}
                        disabled={durationSaving}
                      >
                        {durationSaving ? "..." : "Save"}
                      </button>
                      <button
                        class="btn-inline btn-inline-secondary"
                        onclick={() => (editingDuration = false)}
                        disabled={durationSaving}
                      >
                        Cancel
                      </button>
                      {#if liveRaceDuration !== null}
                        <button
                          class="btn-inline btn-inline-secondary"
                          onclick={() => saveDuration(null)}
                          disabled={durationSaving}
                        >
                          Disable
                        </button>
                      {/if}
                    </div>
                    {#if durationError}
                      <span class="schedule-error">{durationError}</span>
                    {/if}
                  </div>
                {:else if liveRaceDuration !== null}
                  <span class="value">
                    {formatMinutes(liveRaceDuration)}
                    {#if isOrganizer}
                      <button class="btn-edit" onclick={startEditDuration}
                        >Edit</button
                      >
                    {/if}
                  </span>
                {:else}
                  <span class="value">
                    Disabled
                    <button class="btn-edit" onclick={startEditDuration}
                      >Enable</button
                    >
                  </span>
                {/if}
              </div>
            {/if}
          {/if}
          {#if startedAt}
            <div class="info-item">
              <span class="label">Started</span>
              <span class="value">{formatDate(startedAt)}</span>
            </div>
          {/if}
        </div>
      </div>

      {#if customRuleLines.length > 0 || (isOrganizer && canEditRules)}
        <div class="race-rules-card">
          <div class="race-rules-head">
            <h3>Race Rules</h3>
            {#if isOrganizer && canEditRules && !editingRules}
              <button class="btn-edit" onclick={startEditRules}>
                {customRuleLines.length > 0 ? "Edit" : "Add"}
              </button>
            {/if}
          </div>
          {#if editingRules}
            <textarea
              class="race-rules-input"
              bind:value={rulesInput}
              maxlength="1000"
              rows="5"
              placeholder="One rule per line"
              disabled={rulesSaving}
            ></textarea>
            <div class="schedule-edit-actions">
              <button
                class="btn-inline"
                onclick={saveRules}
                disabled={rulesSaving}
              >
                {rulesSaving ? "..." : "Save"}
              </button>
              <button
                class="btn-inline btn-inline-secondary"
                onclick={() => (editingRules = false)}
                disabled={rulesSaving}
              >
                Cancel
              </button>
            </div>
            {#if rulesError}
              <span class="schedule-error">{rulesError}</span>
            {/if}
          {:else if customRuleLines.length > 0}
            <ul class="race-rules-list">
              {#each customRuleLines as line}
                <li>{line}</li>
              {/each}
            </ul>
          {/if}
        </div>
      {/if}

      {#if initialRace.pool_config}
        <PoolSettingsCard
          poolName={initialRace.pool_name || "standard"}
          poolConfig={initialRace.pool_config}
        />
      {/if}
    </main>

    {#if showChatSidebar}
      <ChatSidebar
        messagesParticipants={raceStore.chatMessagesParticipants}
        messagesPublic={raceStore.chatMessagesPublic}
        historyVersion={raceStore.chatHistoryVersion}
        canSend={canSendChat}
        collapsed={chatCollapsed}
        participantsAccess={hasParticipantsAccess}
        {publicAccess}
        {publicLockedReason}
        activeTab={effectiveActiveTab}
        onSend={sendChatMessage}
        onToggle={() => (chatCollapsed = !chatCollapsed)}
        onTabChange={(tab) => (chatActiveTab = tab)}
      />
    {/if}

    {#if showObsModal}
      <ObsOverlayModal
        raceId={initialRace.id}
        onClose={() => (showObsModal = false)}
      />
    {/if}

    {#if showDownloadModal}
      <DownloadModal
        {downloading}
        error={downloadError}
        rules={initialRace.pool_config?.rules ?? null}
        customRules={liveCustomRules}
        onClose={() => (showDownloadModal = false)}
        onDownload={handleDownload}
      />
    {/if}

    {#if pendingConfirm}
      <ConfirmModal
        title={pendingConfirm.title}
        message={pendingConfirm.message}
        confirmLabel={pendingConfirm.confirmLabel}
        danger={pendingConfirm.danger ?? false}
        onConfirm={async () => {
          const action = pendingConfirm?.action;
          pendingConfirm = null;
          if (action) await action();
        }}
        onCancel={() => (pendingConfirm = null)}
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
        onClose={() => (showFeedback = false)}
      />
    {/if}
  </div>
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

  .race-page {
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
    min-height: 0;
  }

  .sidebar-section {
    flex: 1;
    display: flex;
    flex-direction: column;
    overflow-y: auto;
  }

  .sidebar-section h2 {
    color: var(--color-gold);
    margin: 0 0 1rem 0;
    font-size: var(--font-size-lg);
    font-weight: 600;
  }

  .leaderboard-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    margin-bottom: 1rem;
  }

  .leaderboard-header h2 {
    margin: 0;
  }

  .participant-list {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
    overflow-y: auto;
  }

  .invite-btn {
    margin-top: 0.75rem;
    width: 100%;
    padding: 0.75rem;
    border: 2px dashed var(--color-border);
    border-radius: var(--radius-sm);
    background: none;
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-base);
    cursor: pointer;
    transition: all var(--transition);
  }

  .invite-btn:hover {
    border-color: var(--color-purple);
    color: var(--color-purple);
  }

  .join-btn {
    margin-top: 0.75rem;
    width: 100%;
    padding: 0.75rem;
    border: 2px dashed var(--color-success, #10b981);
    border-radius: var(--radius-sm);
    background: none;
    color: var(--color-success, #10b981);
    font-family: var(--font-family);
    font-size: var(--font-size-base);
    font-weight: 500;
    cursor: pointer;
    transition: all var(--transition);
  }

  .join-btn:hover:not(:disabled) {
    background: rgba(16, 185, 129, 0.1);
  }

  .join-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .join-btn.disabled {
    border-color: var(--color-border);
    color: var(--color-text-disabled);
    cursor: not-allowed;
    opacity: 0.6;
  }

  .leave-btn {
    margin-top: 0.5rem;
    width: 100%;
    padding: 0.5rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: none;
    color: var(--color-text-disabled);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    cursor: pointer;
    transition: all var(--transition);
  }

  .leave-btn:hover:not(:disabled) {
    border-color: var(--color-danger, #ef4444);
    color: var(--color-danger, #ef4444);
  }

  .leave-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .login-hint {
    margin: 0.75rem 0 0;
    color: var(--color-text-disabled);
    font-size: var(--font-size-sm);
    text-align: center;
  }

  .login-hint a {
    color: var(--color-purple);
  }

  .join-leave-error {
    margin: 0.5rem 0 0;
    color: var(--color-danger, #ef4444);
    font-size: var(--font-size-sm);
  }

  .invite-search {
    margin-top: 0.75rem;
  }

  .sidebar-footer {
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-top: 1rem;
    margin-top: auto;
    border-top: 1px solid var(--color-border);
  }

  .main-content {
    flex: 1;
    padding: 2rem;
    display: flex;
    flex-direction: column;
    gap: 1.5rem;
    overflow-y: auto;
  }

  .race-header {
    display: flex;
    justify-content: space-between;
    align-items: flex-start;
  }

  .race-header h1 {
    margin: 0;
    color: var(--color-text);
    font-size: var(--font-size-2xl);
    font-weight: 600;
  }

  .race-header h1.frog {
    color: #3e9e5c;
  }

  .race-header h1 .frog-icon {
    width: 1em;
    height: 1em;
    vertical-align: -0.12em;
    margin-right: 0.35rem;
  }

  .header-right {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-shrink: 0;
  }

  .elapsed-clock {
    font-size: var(--font-size-lg);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
    color: var(--color-warning, #f59e0b);
    font-family: "JetBrains Mono", "Fira Code", monospace;
  }

  .organizer {
    margin: 0.25rem 0 0 0;
    color: var(--color-text-disabled);
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

  .race-info {
    background: var(--color-surface);
    border-radius: var(--radius-lg);
    padding: 1.5rem;
  }

  .info-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
    gap: 1rem;
  }

  .info-item {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .label {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 500;
  }

  .value {
    font-weight: 500;
    font-variant-numeric: tabular-nums;
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

  .schedule-edit {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .schedule-edit-actions {
    display: flex;
    gap: 0.5rem;
  }

  .btn-inline {
    background: none;
    border: none;
    padding: 0;
    color: var(--color-purple);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    cursor: pointer;
    font-weight: 500;
  }

  .btn-inline:hover {
    text-decoration: underline;
  }

  .btn-inline:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .btn-inline-secondary {
    color: var(--color-text-disabled);
  }

  .btn-edit {
    background: none;
    border: none;
    padding: 0;
    margin-left: 0.5rem;
    color: var(--color-purple);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    cursor: pointer;
  }

  .btn-edit:hover {
    text-decoration: underline;
  }

  .schedule-error {
    color: var(--color-danger);
    font-size: var(--font-size-xs);
  }

  .inline-minutes {
    display: flex;
    align-items: center;
    gap: 0.35rem;
  }

  .inline-duration {
    width: 5rem;
    padding: 0.25rem 0.5rem;
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
  }

  .waiting-seeds {
    margin: 0;
    padding: 0.75rem;
    text-align: center;
    color: var(--color-text-disabled);
    font-size: var(--font-size-sm);
    font-style: italic;
  }

  .sidebar-download-btn {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: center;
    gap: 0.5rem;
    padding: 0.65rem 1rem;
    margin-top: 0.75rem;
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

  .obs-overlay-btn {
    width: 100%;
    margin-top: 0.5rem;
    padding: 0.5rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: none;
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    cursor: pointer;
    transition: all var(--transition);
  }

  .obs-overlay-btn:hover {
    border-color: var(--color-purple);
    color: var(--color-purple);
  }

  :global(.race-page .zoomable-container) {
    min-height: 400px;
  }

  :global(.race-page .zoomable-container svg) {
    min-height: 400px;
  }

  @media (max-width: 768px) {
    .race-page {
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

    .race-header {
      flex-direction: column;
      gap: 0.5rem;
    }

    .race-header h1 {
      font-size: var(--font-size-xl);
    }

    .info-grid {
      grid-template-columns: 1fr 1fr;
    }
  }

  .dag-wrapper {
    position: relative;
  }

  .go-overlay {
    position: absolute;
    inset: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: rgba(0, 0, 0, 0.6);
    backdrop-filter: blur(3px);
    z-index: 10;
    animation: go-fade 3s ease-out forwards;
    pointer-events: none;
  }

  .go-text {
    font-size: 5rem;
    font-weight: 800;
    color: var(--color-success, #10b981);
    text-shadow:
      0 0 20px rgba(16, 185, 129, 0.5),
      0 2px 4px rgba(0, 0, 0, 0.8);
    animation: go-scale 3s ease-out forwards;
  }

  @keyframes go-fade {
    0% {
      opacity: 1;
    }
    70% {
      opacity: 1;
    }
    100% {
      opacity: 0;
    }
  }

  @keyframes go-scale {
    0% {
      transform: scale(1.4);
    }
    15% {
      transform: scale(1);
    }
    70% {
      transform: scale(1);
    }
    100% {
      transform: scale(0.9);
    }
  }

  .countdown-overlay {
    animation: none;
  }

  .countdown-text {
    font-size: 6rem;
    font-weight: 800;
    color: var(--color-warning, #f59e0b);
    text-shadow:
      0 0 20px rgba(245, 158, 11, 0.5),
      0 2px 4px rgba(0, 0, 0, 0.8);
    animation: countdown-pulse 1s ease-out infinite;
    font-variant-numeric: tabular-nums;
  }

  @keyframes countdown-pulse {
    0% {
      transform: scale(1.2);
      opacity: 1;
    }
    50% {
      transform: scale(1);
      opacity: 0.9;
    }
    100% {
      transform: scale(0.95);
      opacity: 0.8;
    }
  }

  .visibility-badge {
    font-size: var(--font-size-xs);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.15em 0.5em;
    border-radius: var(--radius);
    background: rgba(107, 114, 128, 0.2);
    color: var(--color-text-disabled);
  }

  .abandon-section {
    padding-top: 0.75rem;
    border-top: 1px solid var(--color-border);
  }

  /* Intentional departure from flat design charter:
	   skeuomorphic "big red button" for dramatic effect */
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
    /* Faster than --transition for snappy press-down feel */
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

  .race-ends-pill {
    padding: 0.2rem 0.5rem;
    background: rgba(200, 164, 78, 0.12);
    border: 1px solid rgba(200, 164, 78, 0.35);
    border-radius: var(--radius-sm);
    color: var(--color-warning, #c8a44e);
    font-size: var(--font-size-xs);
    font-weight: 500;
    font-variant-numeric: tabular-nums;
    white-space: nowrap;
  }

  .race-rules-card {
    background: var(--color-bg);
    border: 1px solid var(--color-border);
    border-left: 3px solid var(--color-gold);
    border-radius: var(--radius-sm);
    padding: 0.75rem 1rem;
  }
  .race-rules-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 0.5rem;
  }
  .race-rules-head h3 {
    margin: 0;
    font-size: var(--font-size-base);
    color: var(--color-text);
  }
  .race-rules-list {
    margin: 0.5rem 0 0;
    padding-left: 1.25rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
  .race-rules-input {
    width: 100%;
    margin-top: 0.5rem;
    background: var(--color-surface);
    color: var(--color-text);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0.5rem 0.75rem;
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    resize: vertical;
  }

  .race-rules-input:disabled {
    opacity: 0.6;
    cursor: not-allowed;
  }
</style>
