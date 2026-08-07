<script lang="ts">
  import { tick } from "svelte";
  import { goto } from "$app/navigation";
  import { auth } from "$lib/stores/auth.svelte";
  import {
    fetchAdminUsers,
    updateAdminUserRole,
    fetchAdminPools,
    setAdminPoolEnabled,
    adminDiscardPool,
    adminScanPool,
    fetchAdminActivity,
    fetchAdminRaces,
    deleteRace,
    adminRecalculateStats,
    fetchReportedSeeds,
    resolveReportedSeed,
    fetchAdminAnalytics,
    adminListFeedback,
    fetchAdminDailySchedule,
    updateAdminDailySchedule,
    type AdminUser,
    type AdminPool,
    type Race,
    type ActivityTimeline,
    type ReportedSeed,
    type AdminAnalytics,
    type AdminFeedbackItem,
    type FeedbackSource,
    type AdminDailyScheduleEntry,
    type AdminDailySchedulePoolOption,
  } from "$lib/api";
  import { statusLabel } from "$lib/format";
  import { formatPoolName } from "$lib/utils/format";
  import { Chart, registerables } from "chart.js";
  Chart.register(...registerables);

  type Tab =
    | "stats"
    | "activity"
    | "races"
    | "users"
    | "feedback"
    | "seeds"
    | "daily";
  let activeTab: Tab = $state("stats");

  let users: AdminUser[] = $state([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let authChecked = $state(false);

  type UserSortKey =
    | "username"
    | "training_count"
    | "race_count"
    | "daily_count"
    | "last_seen"
    | "created_at";
  let userSortKey = $state<UserSortKey>("last_seen");
  let userSortAsc = $state(false);

  let sortedUsers = $derived.by(() => {
    const list = [...users];
    list.sort((a, b) => {
      let cmp = 0;
      if (userSortKey === "username") {
        const nameA = (
          a.twitch_display_name || a.twitch_username
        ).toLowerCase();
        const nameB = (
          b.twitch_display_name || b.twitch_username
        ).toLowerCase();
        cmp = nameA.localeCompare(nameB);
      } else if (
        userSortKey === "training_count" ||
        userSortKey === "race_count" ||
        userSortKey === "daily_count"
      ) {
        cmp = a[userSortKey] - b[userSortKey];
      } else {
        const va = a[userSortKey];
        const vb = b[userSortKey];
        const ta = va ? new Date(va).getTime() : 0;
        const tb = vb ? new Date(vb).getTime() : 0;
        cmp = ta - tb;
      }
      return userSortAsc ? cmp : -cmp;
    });
    return list;
  });

  function handleUserSort(key: UserSortKey) {
    if (userSortKey === key) {
      userSortAsc = !userSortAsc;
    } else {
      userSortKey = key;
      userSortAsc = key === "username";
    }
  }

  function userSortIndicator(key: UserSortKey): string {
    if (userSortKey !== key) return "";
    return userSortAsc ? " \u25B2" : " \u25BC";
  }

  let adminPools: AdminPool[] = $state([]);
  let seedsLoading = $state(false);
  let actionLoading = $state<Record<string, boolean>>({});

  let activity: ActivityTimeline | null = $state(null);
  let activityLoading = $state(false);
  let activityLoadingMore = $state(false);

  let inflightRaces: Race[] = $state([]);
  let racesLoading = $state(false);
  let racesLoaded = $state(false);

  let recalcLoading = $state(false);
  let recalcMessage = $state<{
    type: "success" | "error";
    text: string;
  } | null>(null);

  let reportedSeeds: ReportedSeed[] = $state([]);
  let reportedLoading = $state(false);

  let analytics: AdminAnalytics | null = $state(null);
  let analyticsLoading = $state(false);

  let feedbackItems: AdminFeedbackItem[] = $state([]);
  let feedbackTotal = $state(0);
  let feedbackAvg: number | null = $state(null);
  let feedbackDist: Record<string, number> = $state({});
  let feedbackRatingFilter: "" | "1-2" | "3" | "4-5" = $state("");
  let feedbackSourceFilter: "" | FeedbackSource = $state("");
  let feedbackLoading = $state(false);
  let feedbackLoaded = $state(false);
  let feedbackError: string | null = $state(null);

  let dailySchedule: AdminDailyScheduleEntry[] = $state([]);
  let dailyAvailablePools: AdminDailySchedulePoolOption[] = $state([]);
  let dailyLoading = $state(false);
  let dailyLoaded = $state(false);

  $effect(() => {
    if (auth.initialized && !authChecked) {
      authChecked = true;
      if (!auth.isAdmin) {
        goto("/");
        return;
      }
      switchTab(activeTab);
    }
  });

  async function loadUsers() {
    try {
      users = await fetchAdminUsers();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load users.";
    } finally {
      loading = false;
    }
  }

  async function loadSeedStats() {
    seedsLoading = true;
    try {
      adminPools = await fetchAdminPools();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load seed stats.";
    } finally {
      seedsLoading = false;
    }
  }

  async function handleTogglePool(poolName: string, enabled: boolean) {
    actionLoading = { ...actionLoading, [`toggle_${poolName}`]: true };
    try {
      const updated = await setAdminPoolEnabled(poolName, enabled);
      const idx = adminPools.findIndex((p) => p.name === updated.name);
      if (idx !== -1) {
        adminPools[idx] = updated;
      }
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to update pool.";
    } finally {
      actionLoading = { ...actionLoading, [`toggle_${poolName}`]: false };
    }
  }

  async function loadActivity() {
    activityLoading = true;
    try {
      activity = await fetchAdminActivity();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load activity.";
    } finally {
      activityLoading = false;
    }
  }

  async function loadMoreActivity() {
    if (!activity || !activity.has_more) return;
    activityLoadingMore = true;
    try {
      const more = await fetchAdminActivity(activity.items.length);
      activity = {
        items: [...activity.items, ...more.items],
        total: more.total,
        has_more: more.has_more,
      };
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load more activity.";
    } finally {
      activityLoadingMore = false;
    }
  }

  async function loadInflightRaces() {
    racesLoading = true;
    try {
      inflightRaces = await fetchAdminRaces();
      racesLoaded = true;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load races.";
    } finally {
      racesLoading = false;
    }
  }

  async function handleRemoveRace(race: Race) {
    if (!confirm(`Remove race "${race.name}"? This cannot be undone.`)) return;
    actionLoading = { ...actionLoading, [`remove_${race.id}`]: true };
    try {
      await deleteRace(race.id);
      inflightRaces = inflightRaces.filter((r) => r.id !== race.id);
      error = null;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to remove race.";
    } finally {
      actionLoading = { ...actionLoading, [`remove_${race.id}`]: false };
    }
  }

  function switchTab(tab: Tab) {
    activeTab = tab;
    if (tab === "users" && users.length === 0 && loading) {
      loadUsers();
    }
    if (tab === "seeds" && adminPools.length === 0) {
      loadSeedStats();
      loadReportedSeeds();
    }
    if (tab === "stats" && !analytics) {
      loadAnalytics();
    }
    if (tab === "activity" && !activity) {
      loadActivity();
    }
    // Refetch on every open so the monitoring view stays current.
    if (tab === "races") {
      loadInflightRaces();
    }
    if (tab === "feedback" && !feedbackLoaded) {
      loadFeedback();
    }
    if (tab === "daily" && !dailyLoaded) {
      loadDailySchedule();
    }
  }

  async function loadDailySchedule() {
    dailyLoading = true;
    try {
      const payload = await fetchAdminDailySchedule();
      dailySchedule = payload.schedule;
      dailyAvailablePools = payload.available_pools;
      dailyLoaded = true;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load daily schedule.";
    } finally {
      dailyLoading = false;
    }
  }

  const DAY_LABELS = [
    "Monday",
    "Tuesday",
    "Wednesday",
    "Thursday",
    "Friday",
    "Saturday",
    "Sunday",
  ];

  const DAILY_ROTATION_HOUR = 8;

  function todayWeekday(): number {
    // Mirror the backend's daily_date_for: rotation starts at 08:00 UTC.
    const shifted = new Date(Date.now() - DAILY_ROTATION_HOUR * 60 * 60 * 1000);
    const jsDay = shifted.getUTCDay(); // 0=Sun, 1=Mon, ..., 6=Sat
    return (jsDay + 6) % 7; // 0=Mon, ..., 6=Sun
  }

  let currentWeekday = $derived(todayWeekday());

  async function handleScheduleChange(
    weekday: number,
    select: HTMLSelectElement,
  ) {
    const key = `daily_${weekday}`;
    actionLoading = { ...actionLoading, [key]: true };
    try {
      const updated = await updateAdminDailySchedule(weekday, {
        pool_name: select.value,
      });
      const idx = dailySchedule.findIndex(
        (row) => row.weekday === updated.weekday,
      );
      if (idx !== -1) {
        dailySchedule[idx] = updated;
      }
      error = null;
    } catch (e) {
      error =
        e instanceof Error ? e.message : "Failed to update daily schedule.";
      // Reload, then write the persisted value back onto the element
      // directly: Svelte caches the last value it rendered and skips the
      // DOM write when a re-render lands on that same value, so the user's
      // rejected choice would otherwise stay visible. The tick() makes sure
      // the reloaded options are in the DOM before the value is assigned.
      await loadDailySchedule();
      await tick();
      const row = dailySchedule.find((r) => r.weekday === weekday);
      if (row) select.value = row.pool_name;
    } finally {
      actionLoading = { ...actionLoading, [key]: false };
    }
  }

  async function handleDeathlessChange(
    weekday: number,
    input: HTMLInputElement,
  ) {
    const key = `daily_${weekday}`;
    actionLoading = { ...actionLoading, [key]: true };
    try {
      const updated = await updateAdminDailySchedule(weekday, {
        deathless: input.checked,
      });
      const idx = dailySchedule.findIndex(
        (row) => row.weekday === updated.weekday,
      );
      if (idx !== -1) {
        dailySchedule[idx] = updated;
      }
      error = null;
    } catch (e) {
      error =
        e instanceof Error ? e.message : "Failed to update daily schedule.";
      // Same DOM write-back as handleScheduleChange, for the same reason.
      await loadDailySchedule();
      await tick();
      const row = dailySchedule.find((r) => r.weekday === weekday);
      if (row) input.checked = row.deathless;
    } finally {
      actionLoading = { ...actionLoading, [key]: false };
    }
  }

  async function loadReportedSeeds() {
    reportedLoading = true;
    try {
      reportedSeeds = await fetchReportedSeeds();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load reported seeds.";
    } finally {
      reportedLoading = false;
    }
  }

  async function loadAnalytics() {
    analyticsLoading = true;
    try {
      analytics = await fetchAdminAnalytics();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load analytics.";
    } finally {
      analyticsLoading = false;
    }
  }

  async function loadFeedback() {
    feedbackLoading = true;
    feedbackError = null;
    try {
      const params: Parameters<typeof adminListFeedback>[0] = { limit: 50 };
      if (feedbackSourceFilter) params.source = feedbackSourceFilter;
      if (feedbackRatingFilter === "1-2") {
        params.rating_min = 1;
        params.rating_max = 2;
      }
      if (feedbackRatingFilter === "3") {
        params.rating_min = 3;
        params.rating_max = 3;
      }
      if (feedbackRatingFilter === "4-5") {
        params.rating_min = 4;
        params.rating_max = 5;
      }
      const res = await adminListFeedback(params);
      feedbackItems = res.items;
      feedbackTotal = res.total;
      feedbackAvg = res.average_rating;
      feedbackDist = res.distribution;
      feedbackLoaded = true;
    } catch (e) {
      feedbackError =
        e instanceof Error ? e.message : "Failed to load feedback.";
    } finally {
      feedbackLoading = false;
    }
  }

  async function handleResolve(seedId: string, action: "discard" | "restore") {
    actionLoading = { ...actionLoading, [`resolve_${seedId}`]: true };
    try {
      await resolveReportedSeed(seedId, action);
      reportedSeeds = reportedSeeds.filter((s) => s.id !== seedId);
      await loadSeedStats();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to resolve seed.";
    } finally {
      actionLoading = { ...actionLoading, [`resolve_${seedId}`]: false };
    }
  }

  function formatFullDate(dateStr: string): string {
    const d = new Date(dateStr);
    const date = d.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
    const time = d.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    });
    return `${date} ${time}`;
  }

  function formatIgt(ms: number): string {
    if (ms === 0) return "--:--";
    const totalSec = Math.floor(ms / 1000);
    const h = Math.floor(totalSec / 3600);
    const m = Math.floor((totalSec % 3600) / 60);
    const s = totalSec % 60;
    if (h > 0)
      return `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return `${m}:${String(s).padStart(2, "0")}`;
  }

  function placementLabel(p: number): string {
    if (p === 1) return "1st";
    if (p === 2) return "2nd";
    if (p === 3) return "3rd";
    return `${p}th`;
  }

  function placementClass(p: number | null): string {
    if (p === 1) return "gold";
    if (p === 2) return "silver";
    if (p === 3) return "bronze";
    return "";
  }

  async function changeRole(user: AdminUser, newRole: string) {
    try {
      const updated = await updateAdminUserRole(user.id, newRole);
      const idx = users.findIndex((u) => u.id === updated.id);
      if (idx !== -1) {
        users[idx] = updated;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to update role.";
    }
  }

  async function handleDiscard(poolName: string) {
    if (
      !confirm(
        `Discard all available seeds in "${formatPoolName(poolName)}"? This cannot be undone.`,
      )
    )
      return;
    actionLoading = { ...actionLoading, [`discard_${poolName}`]: true };
    try {
      const result = await adminDiscardPool(poolName);
      error = null;
      await loadSeedStats();
      if (result.discarded === 0) {
        error = `No available seeds to discard in "${poolName}".`;
      }
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to discard seeds.";
    } finally {
      actionLoading = { ...actionLoading, [`discard_${poolName}`]: false };
    }
  }

  async function handleScan(poolName: string) {
    actionLoading = { ...actionLoading, [`scan_${poolName}`]: true };
    try {
      await adminScanPool(poolName);
      error = null;
      await loadSeedStats();
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to scan pool.";
    } finally {
      actionLoading = { ...actionLoading, [`scan_${poolName}`]: false };
    }
  }

  async function handleRecalculateStats() {
    recalcLoading = true;
    recalcMessage = null;
    try {
      await adminRecalculateStats();
      recalcMessage = {
        type: "success",
        text: "Stats recalculated successfully.",
      };
    } catch (e) {
      recalcMessage = {
        type: "error",
        text: e instanceof Error ? e.message : "Failed to recalculate stats.",
      };
    } finally {
      recalcLoading = false;
    }
  }

  function formatDate(iso: string | null): string {
    if (!iso) return "Never";
    const d = new Date(iso);
    const pad = (n: number) => String(n).padStart(2, "0");
    return `${pad(d.getDate())}/${pad(d.getMonth() + 1)}/${d.getFullYear()} ${pad(d.getHours())}:${pad(d.getMinutes())}`;
  }

  let activeUsersCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
  let newUsersCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
  let raceSoloCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
  let soloCompletionCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
  let avgParticipantsCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
  let timezoneCanvas: HTMLCanvasElement = $state() as HTMLCanvasElement;
  let charts: Chart[] = [];

  function destroyCharts() {
    charts.forEach((c) => c.destroy());
    charts = [];
  }

  function renderCharts(data: AdminAnalytics) {
    destroyCharts();
    const gridColor = "rgba(255,255,255,0.06)";
    const tickColor = "#888";
    const defaultScales = {
      x: {
        grid: { display: false },
        ticks: { color: tickColor, font: { size: 10 } },
      },
      y: {
        beginAtZero: true,
        grid: { color: gridColor },
        ticks: { color: tickColor, font: { size: 10 } },
      },
    };
    const defaultPlugins = { legend: { display: false } };

    charts.push(
      new Chart(activeUsersCanvas, {
        type: "line",
        data: {
          labels: data.active_users.weeks,
          datasets: [
            {
              label: "Active players",
              data: data.active_users.counts,
              borderColor: "#22c55e",
              backgroundColor: "rgba(34,197,94,0.15)",
              borderWidth: 2,
              fill: true,
              tension: 0.3,
              pointRadius: 2,
            },
          ],
        },
        options: {
          responsive: true,
          plugins: defaultPlugins,
          scales: defaultScales,
        },
      }),
    );

    charts.push(
      new Chart(newUsersCanvas, {
        type: "bar",
        data: {
          labels: data.weekly.weeks,
          datasets: [
            {
              data: data.weekly.new_users,
              backgroundColor: "rgba(139,92,246,0.6)",
              borderColor: "#8b5cf6",
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          plugins: defaultPlugins,
          scales: defaultScales,
        },
      }),
    );

    charts.push(
      new Chart(raceSoloCanvas, {
        type: "bar",
        data: {
          labels: data.weekly.weeks,
          datasets: [
            {
              label: "Races",
              data: data.weekly.races,
              backgroundColor: "rgba(200,164,78,0.6)",
              borderColor: "#c8a44e",
              borderWidth: 1,
            },
            {
              label: "Daily",
              data: data.weekly.daily,
              backgroundColor: "rgba(56,189,248,0.6)",
              borderColor: "#38bdf8",
              borderWidth: 1,
            },
            {
              label: "Solo",
              data: data.weekly.solo,
              backgroundColor: "rgba(139,92,246,0.6)",
              borderColor: "#8b5cf6",
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          scales: {
            x: { ...defaultScales.x, stacked: true },
            y: { ...defaultScales.y, stacked: true },
          },
          plugins: {
            legend: {
              display: true,
              labels: { color: tickColor, font: { size: 10 }, boxWidth: 12 },
            },
          },
        },
      }),
    );

    charts.push(
      new Chart(soloCompletionCanvas, {
        type: "bar",
        data: {
          labels: data.weekly.weeks,
          datasets: [
            {
              label: "Finished",
              data: data.weekly.solo_finished,
              backgroundColor: "rgba(34,197,94,0.5)",
              borderColor: "#22c55e",
              borderWidth: 1,
            },
            {
              label: "Abandoned",
              data: data.weekly.solo_abandoned,
              backgroundColor: "rgba(239,68,68,0.5)",
              borderColor: "#ef4444",
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          scales: {
            x: { ...defaultScales.x, stacked: true },
            y: { ...defaultScales.y, stacked: true },
          },
          plugins: {
            legend: {
              display: true,
              labels: { color: tickColor, font: { size: 10 }, boxWidth: 12 },
            },
          },
        },
      }),
    );

    charts.push(
      new Chart(avgParticipantsCanvas, {
        type: "bar",
        data: {
          labels: data.weekly.weeks,
          datasets: [
            {
              data: data.weekly.avg_participants,
              backgroundColor: "rgba(200,164,78,0.6)",
              borderColor: "#c8a44e",
              borderWidth: 1,
            },
          ],
        },
        options: {
          responsive: true,
          plugins: defaultPlugins,
          scales: defaultScales,
        },
      }),
    );

    if (data.timezones.length > 0) {
      charts.push(
        new Chart(timezoneCanvas, {
          type: "bar",
          data: {
            labels: data.timezones.map((t) => t.timezone.replace(/_/g, " ")),
            datasets: [
              {
                data: data.timezones.map((t) => t.count),
                backgroundColor: "rgba(139,92,246,0.6)",
                borderColor: "#8b5cf6",
                borderWidth: 1,
              },
            ],
          },
          options: {
            responsive: true,
            plugins: defaultPlugins,
            scales: {
              x: {
                grid: { display: false },
                ticks: { color: tickColor, font: { size: 9 }, maxRotation: 45 },
              },
              y: {
                beginAtZero: true,
                grid: { color: gridColor },
                ticks: { color: tickColor, font: { size: 10 }, stepSize: 1 },
              },
            },
          },
        }),
      );
    }
  }

  $effect(() => {
    if (analytics && newUsersCanvas) {
      renderCharts($state.snapshot(analytics));
    }
    return () => destroyCharts();
  });
</script>

<svelte:head>
  <title>Admin - SpeedFog Racing</title>
</svelte:head>

<main>
  <h1>Admin</h1>

  <div class="tabs">
    <button
      class="tab"
      class:active={activeTab === "stats"}
      onclick={() => switchTab("stats")}
    >
      Stats
    </button>
    <button
      class="tab"
      class:active={activeTab === "activity"}
      onclick={() => switchTab("activity")}
    >
      Activity
    </button>
    <button
      class="tab"
      class:active={activeTab === "races"}
      onclick={() => switchTab("races")}
    >
      Races
    </button>
    <button
      class="tab"
      class:active={activeTab === "users"}
      onclick={() => switchTab("users")}
    >
      Users
    </button>
    <button
      class="tab"
      class:active={activeTab === "feedback"}
      onclick={() => switchTab("feedback")}
    >
      Feedback
    </button>
    <button
      class="tab"
      class:active={activeTab === "seeds"}
      onclick={() => switchTab("seeds")}
    >
      Seeds
    </button>
    <button
      class="tab"
      class:active={activeTab === "daily"}
      onclick={() => switchTab("daily")}
    >
      Daily
    </button>
  </div>

  {#if error}
    <div class="error">
      {error}
      <button onclick={() => (error = null)}>&times;</button>
    </div>
  {/if}

  {#if activeTab === "users"}
    {#if loading}
      <p class="loading">Loading users...</p>
    {:else if users.length === 0}
      <p class="empty">No users found.</p>
    {:else}
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>
                <button
                  class="sort-btn"
                  onclick={() => handleUserSort("username")}
                >
                  User{userSortIndicator("username")}
                </button>
              </th>
              <th>Role</th>
              <th class="num-col">
                <button
                  class="sort-btn"
                  onclick={() => handleUserSort("training_count")}
                >
                  Solo{userSortIndicator("training_count")}
                </button>
              </th>
              <th class="num-col">
                <button
                  class="sort-btn"
                  onclick={() => handleUserSort("race_count")}
                >
                  Races{userSortIndicator("race_count")}
                </button>
              </th>
              <th class="num-col">
                <button
                  class="sort-btn"
                  onclick={() => handleUserSort("daily_count")}
                >
                  Daily{userSortIndicator("daily_count")}
                </button>
              </th>
              <th>
                <button
                  class="sort-btn"
                  onclick={() => handleUserSort("last_seen")}
                >
                  Last Seen{userSortIndicator("last_seen")}
                </button>
              </th>
              <th>
                <button
                  class="sort-btn"
                  onclick={() => handleUserSort("created_at")}
                >
                  Joined{userSortIndicator("created_at")}
                </button>
              </th>
            </tr>
          </thead>
          <tbody>
            {#each sortedUsers as user (user.id)}
              <tr>
                <td class="user-cell">
                  {#if user.twitch_avatar_url}
                    <img src={user.twitch_avatar_url} alt="" class="avatar" />
                  {/if}
                  <a href="/user/{user.twitch_username}" class="username-link">
                    {user.twitch_display_name || user.twitch_username}
                  </a>
                </td>
                <td>
                  {#if user.role === "admin"}
                    <span class="role-badge admin">admin</span>
                  {:else}
                    <select
                      value={user.role}
                      onchange={(e) => changeRole(user, e.currentTarget.value)}
                    >
                      <option value="user">user</option>
                      <option value="organizer">organizer</option>
                    </select>
                  {/if}
                </td>
                <td class="num-cell">{user.training_count}</td>
                <td class="num-cell">{user.race_count}</td>
                <td class="num-cell">{user.daily_count}</td>
                <td class="date-cell">{formatDate(user.last_seen)}</td>
                <td class="date-cell">{formatDate(user.created_at)}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {:else if activeTab === "seeds"}
    {#if seedsLoading || reportedLoading}
      <p class="loading">Loading seed stats...</p>
    {:else if adminPools.length === 0}
      <p class="empty">No seed pools found.</p>
    {:else}
      <div class="reported-section">
        <h2 class="section-title">Reported Seeds</h2>
        {#if reportedSeeds.length > 0}
          <div class="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Seed</th>
                  <th>Pool</th>
                  <th>Reporter</th>
                  <th>Reason</th>
                  <th>Date</th>
                  <th>Actions</th>
                </tr>
              </thead>
              <tbody>
                {#each reportedSeeds as seed (seed.id)}
                  <tr>
                    <td class="mono">{seed.seed_number}</td>
                    <td
                      >{seed.pool_display_name ||
                        formatPoolName(seed.pool_name)}</td
                    >
                    <td>{seed.reported_by}</td>
                    <td class="reason-cell" title={seed.reported_reason || ""}
                      >{seed.reported_reason || "-"}</td
                    >
                    <td class="date-cell">{formatDate(seed.reported_at)}</td>
                    <td class="actions-cell">
                      <button
                        class="action-btn discard"
                        disabled={actionLoading[`resolve_${seed.id}`]}
                        onclick={() => handleResolve(seed.id, "discard")}
                      >
                        Discard
                      </button>
                      <button
                        class="action-btn scan"
                        disabled={actionLoading[`resolve_${seed.id}`]}
                        onclick={() => handleResolve(seed.id, "restore")}
                      >
                        Restore
                      </button>
                    </td>
                  </tr>
                {/each}
              </tbody>
            </table>
          </div>
        {:else}
          <p class="empty">No reported seeds.</p>
        {/if}
      </div>
      <h2 class="section-title">Seed Pools</h2>
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Pool Name</th>
              <th>Visible</th>
              <th class="num-col">Available</th>
              <th class="num-col">Consumed</th>
              <th class="num-col">Reported</th>
              <th class="num-col">Discarded</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each [...adminPools].sort( (a, b) => a.name.localeCompare(b.name), ) as pool (pool.name)}
              <tr class:pool-disabled={!pool.enabled}>
                <td class="pool-name"
                  >{pool.display_name ||
                    formatPoolName(pool.name)}{pool.type === "training"
                    ? " (Solo)"
                    : ""}</td
                >
                <td>
                  <label class="pool-toggle">
                    <input
                      type="checkbox"
                      checked={pool.enabled}
                      disabled={actionLoading[`toggle_${pool.name}`]}
                      onchange={(e) =>
                        handleTogglePool(
                          pool.name,
                          (e.currentTarget as HTMLInputElement).checked,
                        )}
                    />
                    <span>{pool.enabled ? "On" : "Off"}</span>
                  </label>
                </td>
                <td class="num-cell">{pool.available}</td>
                <td class="num-cell">{pool.consumed}</td>
                <td class="num-cell">{pool.reported}</td>
                <td class="num-cell">{pool.discarded}</td>
                <td class="actions-cell">
                  <button
                    class="action-btn scan"
                    disabled={actionLoading[`scan_${pool.name}`]}
                    onclick={() => handleScan(pool.name)}
                  >
                    {actionLoading[`scan_${pool.name}`]
                      ? "Scanning..."
                      : "Scan"}
                  </button>
                  <button
                    class="action-btn discard"
                    disabled={actionLoading[`discard_${pool.name}`] ||
                      pool.available === 0}
                    onclick={() => handleDiscard(pool.name)}
                  >
                    {actionLoading[`discard_${pool.name}`]
                      ? "Discarding..."
                      : "Discard"}
                  </button>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {:else if activeTab === "daily"}
    {#if dailyLoading && dailySchedule.length === 0}
      <p class="loading">Loading daily schedule...</p>
    {:else}
      <h2 class="section-title">Daily Seed Schedule</h2>
      <div class="table-wrapper daily-schedule">
        <table>
          <thead>
            <tr>
              <th>Day</th>
              <th>Pool</th>
              <th>Deathless</th>
            </tr>
          </thead>
          <tbody>
            {#each dailySchedule as row (row.weekday)}
              <tr class:today={row.weekday === currentWeekday}>
                <td class="day-cell">
                  {DAY_LABELS[row.weekday]}
                  {#if row.weekday === currentWeekday}
                    <span class="today-badge">Today</span>
                  {/if}
                </td>
                <td>
                  <select
                    value={row.pool_name}
                    disabled={actionLoading[`daily_${row.weekday}`]}
                    onchange={(e) =>
                      handleScheduleChange(row.weekday, e.currentTarget)}
                  >
                    {#each dailyAvailablePools as opt (opt.name)}
                      <option value={opt.name}>{opt.display_name}</option>
                    {/each}
                    {#if !dailyAvailablePools.some((o) => o.name === row.pool_name)}
                      <option value={row.pool_name}>
                        {row.pool_display_name} (unavailable)
                      </option>
                    {/if}
                  </select>
                </td>
                <td class="deathless-cell">
                  <input
                    type="checkbox"
                    checked={row.deathless}
                    disabled={actionLoading[`daily_${row.weekday}`]}
                    onchange={(e) =>
                      handleDeathlessChange(row.weekday, e.currentTarget)}
                    aria-label={`Deathless for ${DAY_LABELS[row.weekday]}`}
                  />
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
      <p class="schedule-note">
        Note: changes to the "Today" row do not affect the current Daily Seed;
        they take effect next week.
      </p>
    {/if}
  {:else if activeTab === "stats"}
    {#if analyticsLoading}
      <p class="loading">Loading analytics...</p>
    {:else if !analytics}
      <p class="empty">
        Failed to load analytics. <button
          class="link-btn"
          onclick={loadAnalytics}>Retry</button
        >
      </p>
    {:else}
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="kpi-label">Total Users</div>
          <div class="kpi-value">{analytics.kpis.total_users}</div>
          <div class="kpi-sub">
            +{analytics.kpis.new_users_this_month} this month
          </div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Active (30d)</div>
          <div class="kpi-value">{analytics.kpis.active_users_30d}</div>
          <div class="kpi-sub">{analytics.kpis.active_users_pct}% of total</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Races (finished)</div>
          <div class="kpi-value kpi-gold">
            {analytics.kpis.total_races_finished}
          </div>
          <div class="kpi-sub">
            avg {analytics.kpis.avg_participants} players
          </div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Daily Participants</div>
          <div class="kpi-value kpi-gold">
            {analytics.kpis.total_daily_participants}
          </div>
          <div class="kpi-sub">qualified runs across all dailies</div>
        </div>
        <div class="kpi-card">
          <div class="kpi-label">Solo Sessions</div>
          <div class="kpi-value kpi-purple">{analytics.kpis.total_solo}</div>
          <div class="kpi-sub">
            {analytics.kpis.solo_completion_pct}% finished
          </div>
        </div>
      </div>

      <div class="chart-box chart-full">
        <div class="chart-title">Active players per week</div>
        <canvas bind:this={activeUsersCanvas}></canvas>
      </div>

      <div class="charts-grid">
        <div class="chart-box">
          <div class="chart-title">New Users per Week</div>
          <canvas bind:this={newUsersCanvas}></canvas>
        </div>
        <div class="chart-box">
          <div class="chart-title">Races, Daily & Solo per Week</div>
          <canvas bind:this={raceSoloCanvas}></canvas>
        </div>
        <div class="chart-box">
          <div class="chart-title">Solo Completion Rate</div>
          <canvas bind:this={soloCompletionCanvas}></canvas>
        </div>
        <div class="chart-box">
          <div class="chart-title">Avg Participants per Race</div>
          <canvas bind:this={avgParticipantsCanvas}></canvas>
        </div>
      </div>

      {@const raceMax = Math.max(1, ...analytics.heatmaps.race_players.flat())}
      {@const soloMax = Math.max(1, ...analytics.heatmaps.solo.flat())}
      {@const hours = [
        "00h",
        "02h",
        "04h",
        "06h",
        "08h",
        "10h",
        "12h",
        "14h",
        "16h",
        "18h",
        "20h",
        "22h",
      ]}
      {@const days = ["Mo", "Tu", "We", "Th", "Fr", "Sa", "Su"]}

      <div class="heatmaps-row">
        <div class="heatmap-box">
          <div class="heatmap-title heatmap-gold">
            Race Players <span class="heatmap-tz">(UTC)</span>
          </div>
          <div class="heatmap-grid">
            <div class="heatmap-corner"></div>
            {#each days as day}
              <div class="heatmap-day">{day}</div>
            {/each}
            {#each hours as hour, rowIdx}
              <div class="heatmap-hour">{hour}</div>
              {#each analytics.heatmaps.race_players[rowIdx] as val}
                <div
                  class="heatmap-cell"
                  style="background: rgba(200,164,78,{(val / raceMax) * 0.9})"
                  title={String(val)}
                ></div>
              {/each}
            {/each}
          </div>
          <div class="heatmap-legend">
            <span>0</span>
            <div class="heatmap-legend-bar heatmap-legend-gold"></div>
            <span>{raceMax}</span>
          </div>
        </div>

        <div class="heatmap-box">
          <div class="heatmap-title heatmap-purple">
            Solo <span class="heatmap-tz">(UTC)</span>
          </div>
          <div class="heatmap-grid">
            <div class="heatmap-corner"></div>
            {#each days as day}
              <div class="heatmap-day">{day}</div>
            {/each}
            {#each hours as hour, rowIdx}
              <div class="heatmap-hour">{hour}</div>
              {#each analytics.heatmaps.solo[rowIdx] as val}
                <div
                  class="heatmap-cell"
                  style="background: rgba(139,92,246,{(val / soloMax) * 0.9})"
                  title={String(val)}
                ></div>
              {/each}
            {/each}
          </div>
          <div class="heatmap-legend">
            <span>0</span>
            <div class="heatmap-legend-bar heatmap-legend-purple"></div>
            <span>{soloMax}</span>
          </div>
        </div>
      </div>

      {#if analytics.timezones.length > 0}
        <div class="chart-box chart-full">
          <div class="chart-title">Players by Timezone</div>
          <canvas bind:this={timezoneCanvas}></canvas>
        </div>
      {/if}

      {@const poolRunsMax = Math.max(
        1,
        ...analytics.pool_usage.flatMap((p) => [p.race_runs, p.training_runs]),
      )}
      <div class="charts-grid">
        <div class="chart-box">
          <div class="chart-title">Pool Usage</div>
          {#if analytics.pool_usage.length === 0}
            <p class="analytics-table-empty">No runs recorded yet.</p>
          {:else}
            <table class="analytics-table">
              <thead>
                <tr>
                  <th>Pool</th>
                  <th>Type</th>
                  <th class="th-runs">Runs</th>
                </tr>
              </thead>
              <tbody>
                {#each analytics.pool_usage as pool (pool.pool_name)}
                  {@const hasRace = pool.race_runs > 0}
                  {@const hasTraining = pool.training_runs > 0}
                  {@const rowCount = (hasRace ? 1 : 0) + (hasTraining ? 1 : 0)}
                  {#if hasRace}
                    <tr class="race-row">
                      <td class="pool-name" rowspan={rowCount}>
                        {pool.pool_display_name ||
                          formatPoolName(pool.pool_name)}
                      </td>
                      <td class="type-label race-type">Race</td>
                      <td class="runs-cell">
                        <div
                          class="runs-bar runs-bar-race"
                          style="width: {Math.max(
                            12,
                            (pool.race_runs / poolRunsMax) * 120,
                          )}px"
                        ></div>
                        <span class="runs-value">{pool.race_runs}</span>
                      </td>
                    </tr>
                  {/if}
                  {#if hasTraining}
                    <tr class={hasRace ? "training-row" : "training-row-first"}>
                      {#if !hasRace}
                        <td class="pool-name" rowspan={rowCount}>
                          {pool.pool_display_name ||
                            formatPoolName(pool.pool_name)}
                        </td>
                      {/if}
                      <td class="type-label training-type">Solo</td>
                      <td class="runs-cell">
                        <div
                          class="runs-bar runs-bar-training"
                          style="width: {Math.max(
                            12,
                            (pool.training_runs / poolRunsMax) * 120,
                          )}px"
                        ></div>
                        <span class="runs-value">{pool.training_runs}</span>
                      </td>
                    </tr>
                  {/if}
                {/each}
              </tbody>
            </table>
          {/if}
        </div>
        <div class="chart-box">
          <div class="chart-title">Top Race Organizers</div>
          {#if analytics.top_organizers.length === 0}
            <p class="analytics-table-empty">No finished races yet.</p>
          {:else}
            <table class="analytics-table">
              <thead>
                <tr>
                  <th class="rank-col">#</th>
                  <th>User</th>
                  <th class="num">Races</th>
                  <th class="num">Avg Players</th>
                </tr>
              </thead>
              <tbody>
                {#each analytics.top_organizers as org, idx (org.user_id)}
                  <tr>
                    <td class="rank-col num">{idx + 1}</td>
                    <td>
                      <a
                        href="/user/{org.twitch_username}"
                        class="organizer-link"
                        title={org.twitch_display_name || org.twitch_username}
                      >
                        {#if org.twitch_avatar_url}
                          <img
                            src={org.twitch_avatar_url}
                            alt=""
                            class="organizer-avatar"
                          />
                        {/if}
                        <span class="organizer-name"
                          >{org.twitch_display_name ||
                            org.twitch_username}</span
                        >
                      </a>
                    </td>
                    <td class="num">{org.race_count}</td>
                    <td class="num">{org.avg_participants.toFixed(1)}</td>
                  </tr>
                {/each}
              </tbody>
            </table>
          {/if}
        </div>
      </div>

      <div class="stats-section">
        <h2 class="section-title">Recalculate</h2>
        <p class="stats-description">
          Recompute cached statistics for all users and participants from raw
          race data.
        </p>
        <div class="stats-actions">
          <button
            class="action-btn recalc"
            disabled={recalcLoading}
            onclick={handleRecalculateStats}
          >
            {recalcLoading ? "Recalculating..." : "Recalculate Stats"}
          </button>
          {#if recalcMessage}
            <span class="recalc-message {recalcMessage.type}"
              >{recalcMessage.text}</span
            >
          {/if}
        </div>
      </div>
    {/if}
  {:else if activeTab === "activity"}
    {#if activityLoading}
      <p class="loading">Loading activity...</p>
    {:else if !activity || activity.items.length === 0}
      <p class="empty">No activity yet.</p>
    {:else}
      <div class="timeline">
        {#each activity.items as item (item.type + "-" + ("race_id" in item ? item.race_id : "session_id" in item ? item.session_id : "") + "-" + item.date + "-" + (item.user?.id ?? ""))}
          <div class="activity-card">
            <div class="col-who">
              {#if item.user}
                <a
                  href="/user/{item.user.twitch_username}"
                  class="activity-user"
                >
                  {#if item.user.twitch_avatar_url}
                    <img
                      src={item.user.twitch_avatar_url}
                      alt=""
                      class="activity-avatar"
                    />
                  {/if}
                  <span class="activity-username"
                    >{item.user.twitch_display_name ||
                      item.user.twitch_username}</span
                  >
                </a>
              {/if}
              <span class="activity-date">{formatFullDate(item.date)}</span>
            </div>
            <div class="col-what">
              {#if (item.type === "race_participant" || item.type === "training" || item.type === "daily_participant") && item.is_mod_connected}
                <span
                  class="conn-dot connected"
                  role="img"
                  aria-label="Mod connected"
                  title={item.mod_version
                    ? `Mod connected (v${item.mod_version})`
                    : "Mod connected"}
                ></span>
              {/if}
              {#if item.type === "race_participant" || item.type === "race_organizer" || item.type === "race_caster"}
                <a href="/race/{item.race_id}" class="activity-title"
                  >{item.race_name}</a
                >
              {:else if item.type === "training"}
                <a href="/training/{item.session_id}" class="activity-title"
                  >{item.pool_display_name || formatPoolName(item.pool_name)}</a
                >
              {:else if item.type === "daily_participant"}
                <a href="/daily/{item.daily_date}" class="activity-title"
                  >{item.pool_display_name || formatPoolName(item.pool_name)}</a
                >
              {/if}
            </div>
            <div class="col-context">
              <div class="badge-row">
                {#if item.type === "race_participant"}
                  <span class="activity-badge participant">Race</span>
                  {#if item.is_organizer}
                    <span class="activity-badge organizer">Organized</span>
                  {/if}
                {:else if item.type === "race_organizer"}
                  <span class="activity-badge organizer">Organized</span>
                {:else if item.type === "race_caster"}
                  <span class="activity-badge caster">Casted</span>
                {:else if item.type === "training"}
                  <span class="activity-badge training">Solo</span>
                {:else if item.type === "daily_participant"}
                  <span class="activity-badge daily">Daily</span>
                  {#if item.status === "running"}
                    <span class="activity-badge daily-active">Active</span>
                  {/if}
                {/if}
                <span class="signal signal-{item.status}"
                  >{statusLabel(item.status)}</span
                >
              </div>
              <div class="activity-details">
                {#if item.type === "race_participant"}
                  {#if item.placement}
                    <span class="placement {placementClass(item.placement)}">
                      {placementLabel(item.placement)} / {item.total_starters}
                    </span>
                  {/if}
                  <span class="mono">{formatIgt(item.igt_ms)}</span>
                  <span>{item.death_count} deaths</span>
                {:else if item.type === "race_organizer"}
                  <span>{item.participant_count} players</span>
                {:else if item.type === "training"}
                  <span class="mono">{formatIgt(item.igt_ms)}</span>
                  <span>{item.death_count} deaths</span>
                {:else if item.type === "daily_participant"}
                  {#if item.placement}
                    <span class="placement {placementClass(item.placement)}">
                      {placementLabel(item.placement)} / {item.total_starters}
                    </span>
                  {:else if item.status === "finished"}
                    <span class="placement-dnf"
                      >DNF / {item.total_starters}</span
                    >
                  {/if}
                  <span class="mono">{formatIgt(item.igt_ms)}</span>
                  <span>{item.death_count} deaths</span>
                {/if}
              </div>
            </div>
          </div>
        {/each}
      </div>

      {#if activity.has_more}
        <button
          class="btn btn-secondary load-more"
          disabled={activityLoadingMore}
          onclick={loadMoreActivity}
        >
          {activityLoadingMore ? "Loading..." : "Load more"}
        </button>
      {/if}
    {/if}
  {:else if activeTab === "races"}
    {#if racesLoading && !racesLoaded}
      <p class="loading">Loading races...</p>
    {:else if inflightRaces.length === 0}
      <p class="empty">No races in progress.</p>
    {:else}
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Name</th>
              <th>Organizer</th>
              <th>Status</th>
              <th>Visibility</th>
              <th class="num-col">Players</th>
              <th>When</th>
              <th>Actions</th>
            </tr>
          </thead>
          <tbody>
            {#each inflightRaces as race (race.id)}
              <tr>
                <td>
                  <a href="/race/{race.id}" class="username-link">{race.name}</a
                  >
                </td>
                <td>
                  <!-- Flex lives on an inner wrapper, not the <td>, so the cell
                       keeps vertical-align: middle and lines up with the plain
                       text cells in the row. -->
                  <div class="user-cell">
                    {#if race.organizer.twitch_avatar_url}
                      <img
                        src={race.organizer.twitch_avatar_url}
                        alt=""
                        class="avatar"
                      />
                    {/if}
                    <a
                      href="/user/{race.organizer.twitch_username}"
                      class="username-link"
                    >
                      {race.organizer.twitch_display_name ||
                        race.organizer.twitch_username}
                    </a>
                  </div>
                </td>
                <td>
                  <span class="signal signal-{race.status}"
                    >{statusLabel(race.status)}</span
                  >
                </td>
                <td>
                  <span
                    class="badge {race.is_public
                      ? 'vis-public'
                      : 'vis-private'}"
                    >{race.is_public ? "Public" : "Private"}</span
                  >
                </td>
                <td class="num-cell">{race.participant_count}</td>
                <td class="date-cell">
                  {formatFullDate(
                    race.started_at ?? race.scheduled_at ?? race.created_at,
                  )}
                </td>
                <td>
                  <div class="actions-cell">
                    {#if race.status === "setup"}
                      <button
                        class="action-btn remove"
                        disabled={actionLoading[`remove_${race.id}`]}
                        onclick={() => handleRemoveRace(race)}
                      >
                        {actionLoading[`remove_${race.id}`]
                          ? "Removing..."
                          : "Remove"}
                      </button>
                    {/if}
                  </div>
                </td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {:else if activeTab === "feedback"}
    <div class="feedback-stats">
      <span class="feedback-stat">
        <span class="feedback-stat-label">Total</span>
        <span class="feedback-stat-value">{feedbackTotal}</span>
      </span>
      <span class="feedback-stat">
        <span class="feedback-stat-label">Average</span>
        <span class="feedback-stat-value"
          >{feedbackAvg !== null ? feedbackAvg.toFixed(2) : "-"}</span
        >
      </span>
      {#each [1, 2, 3, 4, 5] as r}
        <span class="feedback-stat">
          <span class="feedback-stat-label">{r}★</span>
          <span class="feedback-stat-value">{feedbackDist[String(r)] ?? 0}</span
          >
        </span>
      {/each}
    </div>

    <div class="feedback-filters">
      <label>
        Rating
        <select bind:value={feedbackRatingFilter} onchange={loadFeedback}>
          <option value="">All</option>
          <option value="1-2">1-2★</option>
          <option value="3">3★</option>
          <option value="4-5">4-5★</option>
        </select>
      </label>
      <label>
        Source
        <select bind:value={feedbackSourceFilter} onchange={loadFeedback}>
          <option value="">All</option>
          <option value="post_first_race">Post first race</option>
          <option value="user_menu">User menu</option>
        </select>
      </label>
    </div>

    {#if feedbackError}
      <p class="empty">{feedbackError}</p>
    {:else if feedbackLoading && feedbackItems.length === 0}
      <p class="loading">Loading feedback...</p>
    {:else if feedbackItems.length === 0}
      <p class="empty">No feedback yet.</p>
    {:else}
      <div class="table-wrapper">
        <table>
          <thead>
            <tr>
              <th>Date</th>
              <th>User</th>
              <th>Rating</th>
              <th>Comment</th>
              <th>Source</th>
              <th>Race</th>
              <th class="num-col">Races played</th>
            </tr>
          </thead>
          <tbody>
            {#each feedbackItems as item (item.id)}
              <tr>
                <td class="date-cell">{formatFullDate(item.created_at)}</td>
                <td>
                  <a
                    href="/user/{item.user.twitch_username}"
                    class="username-link"
                  >
                    {item.user.twitch_display_name || item.user.twitch_username}
                  </a>
                </td>
                <td class="rating-cell"
                  >{"★".repeat(item.rating)}{"☆".repeat(5 - item.rating)}</td
                >
                <td class="comment-cell">{item.comment ?? ""}</td>
                <td>{item.source}</td>
                <td class="mono">
                  {#if item.race}
                    <a href="/race/{item.race.id}" class="username-link"
                      >{item.race.id.slice(0, 8)}</a
                    >
                  {/if}
                </td>
                <td class="num-cell">{item.races_played_at_feedback}</td>
              </tr>
            {/each}
          </tbody>
        </table>
      </div>
    {/if}
  {/if}
</main>

<style>
  main {
    width: 100%;
    max-width: 1200px;
    margin: 0 auto;
    padding: 2rem;
    box-sizing: border-box;
  }

  h1 {
    color: var(--color-text);
    font-size: var(--font-size-2xl);
    font-weight: 600;
    margin-bottom: 1.5rem;
  }

  .tabs {
    display: flex;
    gap: 0;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid var(--color-border);
  }

  .tab {
    padding: 0.6rem 1.25rem;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s;
  }

  .tab:hover {
    color: var(--color-text);
  }

  .tab.active {
    color: var(--color-purple);
    border-bottom-color: var(--color-purple);
  }

  .error {
    background: var(--color-danger-dark);
    color: white;
    padding: 0.75rem 1rem;
    border-radius: var(--radius-sm);
    margin-bottom: 1rem;
    display: flex;
    justify-content: space-between;
    align-items: center;
  }

  .error button {
    background: none;
    border: none;
    color: white;
    font-size: 1.25rem;
    cursor: pointer;
  }

  .loading,
  .empty {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .table-wrapper {
    overflow-x: auto;
  }

  table {
    width: 100%;
    border-collapse: collapse;
  }

  th {
    text-align: left;
    padding: 0.75rem 1rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    border-bottom: 1px solid var(--color-border);
  }

  .sort-btn {
    background: none;
    border: none;
    color: inherit;
    font: inherit;
    text-transform: inherit;
    letter-spacing: inherit;
    cursor: pointer;
    padding: 0;
    transition: color var(--transition);
    white-space: nowrap;
  }

  .sort-btn:hover {
    color: var(--color-purple);
  }

  .num-col .sort-btn {
    width: 100%;
    text-align: center;
  }

  td {
    padding: 0.75rem 1rem;
    border-bottom: 1px solid var(--color-border);
    vertical-align: middle;
  }

  tr:hover td {
    background: var(--color-surface);
  }

  .user-cell {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .avatar {
    width: 32px;
    height: 32px;
    border-radius: 50%;
    border: 2px solid var(--color-border);
  }

  .username-link {
    font-weight: 500;
    color: inherit;
    text-decoration: none;
  }

  .username-link:hover {
    color: var(--color-purple);
    text-decoration: underline;
  }

  .num-col {
    text-align: center;
  }

  .num-cell {
    text-align: center;
    font-family: var(--font-mono);
  }

  .date-cell {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    white-space: nowrap;
  }

  .pool-name {
    font-weight: 500;
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
  }

  .pool-disabled td {
    color: var(--color-text-disabled);
  }

  .pool-disabled .pool-name {
    text-decoration: line-through;
  }

  .pool-toggle {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    cursor: pointer;
    font-size: var(--font-size-sm);
  }

  .actions-cell {
    display: flex;
    gap: 0.5rem;
  }

  .action-btn {
    padding: 0.3rem 0.75rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    cursor: pointer;
    white-space: nowrap;
    transition:
      background 0.15s,
      border-color 0.15s;
  }

  .action-btn:hover:not(:disabled) {
    border-color: var(--color-text-secondary);
  }

  .action-btn:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .action-btn.discard,
  .action-btn.remove {
    color: var(--color-danger-dark);
    border-color: var(--color-danger-dark);
  }

  .action-btn.discard:hover:not(:disabled),
  .action-btn.remove:hover:not(:disabled) {
    background: var(--color-danger-dark);
    color: white;
  }

  .role-badge {
    display: inline-block;
    padding: 0.2rem 0.6rem;
    border-radius: var(--radius-sm);
    font-size: var(--font-size-sm);
    font-weight: 500;
  }

  .role-badge.admin {
    background: rgba(239, 68, 68, 0.15);
    color: var(--color-danger);
  }

  select {
    padding: 0.35rem 0.5rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    cursor: pointer;
  }

  select:focus {
    outline: none;
    border-color: var(--color-purple);
  }

  /* Activity feed styles */
  .timeline {
    display: flex;
    flex-direction: column;
    gap: 0.35rem;
  }

  .activity-card {
    display: grid;
    grid-template-columns: 10rem 1fr auto;
    gap: 0.75rem;
    align-items: center;
    padding: 0.6rem 1rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }

  .col-who {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
  }

  .activity-user {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    text-decoration: none;
    color: inherit;
    min-width: 0;
  }

  .activity-user:hover .activity-username {
    color: var(--color-purple);
    text-decoration: underline;
  }

  .activity-avatar {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    border: 1px solid var(--color-border);
    flex-shrink: 0;
  }

  .activity-username {
    font-size: var(--font-size-sm);
    font-weight: 500;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .activity-date {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    white-space: nowrap;
    padding-left: 1.75rem;
  }

  .col-what {
    min-width: 0;
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .activity-title {
    color: var(--color-text-primary);
    text-decoration: none;
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
    min-width: 0;
  }

  .conn-dot.connected {
    flex-shrink: 0;
    width: 8px;
    height: 8px;
    border-radius: 50%;
    background: var(--color-success, #22c55e);
  }

  .activity-title:hover {
    color: var(--color-purple);
    text-decoration: underline;
  }

  .col-context {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.15rem;
    flex-shrink: 0;
  }

  .badge-row {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  /* Visibility badges in the Races tab. Private is warning-tinted so the
     races an admin can't otherwise see stand out. */
  .vis-public {
    background: rgba(156, 163, 175, 0.15);
    color: var(--color-text-secondary);
  }

  .vis-private {
    background: rgba(200, 164, 78, 0.15);
    color: var(--color-warning);
  }

  .activity-badge {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.1rem 0.4rem;
    border-radius: var(--radius-sm);
    white-space: nowrap;
  }

  .activity-badge.participant {
    background: rgba(200, 164, 78, 0.15);
    color: var(--color-gold);
  }

  .activity-badge.organizer {
    background: rgba(200, 164, 78, 0.15);
    color: var(--color-gold);
  }

  .activity-badge.caster {
    background: rgba(200, 164, 78, 0.15);
    color: var(--color-gold);
  }

  .activity-badge.training {
    background: rgba(169, 155, 201, 0.15);
    color: var(--color-purple);
  }

  .activity-badge.daily {
    background: rgba(45, 212, 191, 0.15);
    color: #2dd4bf;
  }

  .activity-badge.daily-active {
    background: rgba(200, 164, 78, 0.15);
    color: var(--color-gold);
  }

  .activity-details {
    display: flex;
    gap: 0.5rem;
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    white-space: nowrap;
  }

  .placement {
    font-weight: 600;
  }

  .placement.gold {
    color: var(--color-gold);
  }

  .placement.silver {
    color: #c0c0c0;
  }

  .placement.bronze {
    color: #cd7f32;
  }

  .mono {
    font-family: var(--font-mono);
  }

  .load-more {
    margin-top: 1rem;
    width: 100%;
  }

  .btn-secondary {
    padding: 0.5rem 1rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-surface);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    cursor: pointer;
    transition:
      background 0.15s,
      border-color 0.15s;
  }

  .btn-secondary:hover:not(:disabled) {
    border-color: var(--color-text-secondary);
  }

  .btn-secondary:disabled {
    opacity: 0.5;
    cursor: not-allowed;
  }

  .section-title {
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: 0.75rem;
  }

  .stats-description {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    margin-bottom: 1rem;
  }

  .stats-actions {
    display: flex;
    align-items: center;
    gap: 1rem;
  }

  .action-btn.recalc {
    color: var(--color-warning, #d97706);
    border-color: var(--color-warning, #d97706);
  }

  .action-btn.recalc:hover:not(:disabled) {
    background: var(--color-warning, #d97706);
    color: white;
  }

  .recalc-message {
    font-size: var(--font-size-sm);
  }

  .recalc-message.success {
    color: var(--color-success, #22c55e);
  }

  .recalc-message.error {
    color: var(--color-danger, #ef4444);
  }

  .reported-section {
    margin-bottom: 2rem;
  }

  .feedback-stats {
    display: grid;
    grid-template-columns: repeat(7, 1fr);
    gap: 0.75rem;
    margin-bottom: 1rem;
  }

  .feedback-stat {
    display: flex;
    flex-direction: column;
    align-items: center;
    padding: 0.5rem 0.9rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }

  .feedback-stat-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .feedback-stat-value {
    font-size: var(--font-size-lg);
    font-weight: 600;
    color: var(--color-text);
    font-family: var(--font-mono);
  }

  .feedback-filters {
    display: flex;
    flex-wrap: wrap;
    gap: 1rem;
    margin-bottom: 1rem;
  }

  .feedback-filters label {
    display: inline-flex;
    align-items: center;
    gap: 0.4rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .rating-cell {
    color: var(--color-gold);
    white-space: nowrap;
    font-family: var(--font-mono);
  }

  .comment-cell {
    max-width: 40ch;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .reason-cell {
    max-width: 250px;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .link-btn {
    background: none;
    border: none;
    color: var(--color-purple);
    font-family: var(--font-family);
    font-size: inherit;
    cursor: pointer;
    padding: 0;
    text-decoration: underline;
  }

  .kpi-grid {
    display: grid;
    grid-template-columns: repeat(5, 1fr);
    gap: 0.75rem;
    margin-bottom: 1.5rem;
  }

  .kpi-card {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 1rem;
    text-align: center;
  }

  .kpi-label {
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: var(--color-text-secondary);
  }

  .kpi-value {
    font-size: 1.75rem;
    font-weight: 700;
    color: var(--color-text);
    margin: 0.25rem 0;
    font-family: var(--font-mono);
  }

  .kpi-gold {
    color: var(--color-gold);
  }

  .kpi-purple {
    color: var(--color-purple);
  }

  .kpi-sub {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .charts-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
  }

  .chart-box {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 1rem;
  }

  .chart-full {
    margin-bottom: 1.5rem;
  }

  .chart-title {
    font-size: var(--font-size-sm);
    font-weight: 600;
    color: var(--color-text);
    margin-bottom: 0.75rem;
  }

  .analytics-table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.9rem;
  }

  .analytics-table thead th {
    text-align: left;
    padding: 0.4rem 0.6rem;
    color: var(--color-text-secondary);
    font-weight: 500;
    font-size: 0.75rem;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--color-border);
  }

  .analytics-table tbody td {
    padding: 0.4rem 0.6rem;
    color: var(--color-text);
  }

  .analytics-table th.num,
  .analytics-table td.num {
    text-align: right;
    font-family: var(--font-mono);
  }

  .analytics-table .rank-col {
    width: 2.5rem;
  }

  .analytics-table .th-runs {
    width: 50%;
  }

  .analytics-table .runs-cell {
    display: flex;
    align-items: center;
    gap: 0.5rem;
  }

  .analytics-table .runs-bar {
    height: 12px;
    border-radius: 6px;
    flex-shrink: 0;
    transition: width 0.3s ease;
  }

  .analytics-table .runs-bar-race {
    background: var(--color-gold);
  }

  .analytics-table .runs-bar-training {
    background: var(--color-purple);
  }

  .analytics-table .runs-value {
    font-family: var(--font-mono);
    flex-shrink: 0;
  }

  .analytics-table .pool-name {
    font-weight: 600;
    color: var(--color-gold);
    vertical-align: middle;
  }

  .analytics-table .type-label {
    font-size: 0.8rem;
    font-weight: 500;
  }

  .analytics-table .race-type {
    color: var(--color-gold);
  }

  .analytics-table .training-type {
    color: var(--color-purple);
  }

  .analytics-table .race-row td,
  .analytics-table .training-row-first td {
    border-top: 1px solid var(--color-border);
  }

  .analytics-table .training-row td {
    border-top: none;
  }

  .analytics-table tbody tr:first-child td {
    border-top: none;
  }

  .analytics-table-empty {
    color: var(--color-text-secondary);
    font-size: 0.85rem;
    margin: 0.25rem 0 0;
  }

  .organizer-link {
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    color: inherit;
    text-decoration: none;
  }

  .organizer-link:hover .organizer-name {
    text-decoration: underline;
  }

  .organizer-avatar {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    object-fit: cover;
  }

  .organizer-name {
    max-width: 10rem;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .heatmaps-row {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.75rem;
    margin-bottom: 1.5rem;
  }

  .heatmap-box {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 1rem;
  }

  .heatmap-title {
    font-size: var(--font-size-sm);
    font-weight: 600;
    margin-bottom: 0.75rem;
  }

  .heatmap-gold {
    color: var(--color-gold);
  }

  .heatmap-purple {
    color: var(--color-purple);
  }

  .heatmap-tz {
    font-size: 0.65rem;
    font-weight: 400;
    color: var(--color-text-secondary);
    margin-left: 0.25rem;
  }

  .heatmap-grid {
    display: grid;
    grid-template-columns: 2.5rem repeat(7, 1fr);
    gap: 3px;
  }

  .heatmap-corner {
    display: block;
  }

  .heatmap-day {
    text-align: center;
    font-size: 0.6rem;
    color: var(--color-text-secondary);
    padding-bottom: 2px;
  }

  .heatmap-hour {
    text-align: right;
    padding-right: 4px;
    font-size: 0.6rem;
    color: var(--color-text-secondary);
    line-height: 1.5rem;
  }

  .heatmap-cell {
    height: 1.5rem;
    border-radius: 2px;
    background: var(--color-bg, #0d1117);
  }

  .heatmap-legend {
    display: flex;
    align-items: center;
    gap: 6px;
    margin-top: 0.5rem;
    font-size: 0.6rem;
    color: var(--color-text-secondary);
  }

  .heatmap-legend-bar {
    flex: 1;
    height: 8px;
    border-radius: 4px;
    max-width: 120px;
  }

  .heatmap-legend-gold {
    background: linear-gradient(to right, #0d1117, rgba(200, 164, 78, 0.9));
  }

  .heatmap-legend-purple {
    background: linear-gradient(to right, #0d1117, rgba(139, 92, 246, 0.9));
  }

  @media (max-width: 640px) {
    main {
      padding: 1rem;
    }

    h1 {
      font-size: var(--font-size-xl);
    }

    th,
    td {
      padding: 0.5rem;
    }

    .activity-card {
      display: flex;
      flex-direction: column;
      gap: 0.25rem;
    }

    .activity-date {
      padding-left: 0;
    }

    .col-context {
      align-items: flex-start;
    }

    .kpi-grid {
      grid-template-columns: repeat(2, 1fr);
    }

    .feedback-stats {
      grid-template-columns: repeat(4, 1fr);
    }

    .charts-grid,
    .heatmaps-row {
      grid-template-columns: 1fr;
    }
  }

  .daily-schedule {
    max-width: 28rem;
  }

  .daily-schedule .day-cell {
    font-weight: 500;
  }

  .daily-schedule tr.today td {
    background: var(--color-bg-elevated, rgba(200, 164, 78, 0.08));
  }

  .today-badge {
    display: inline-block;
    margin-left: 0.5rem;
    padding: 0.05rem 0.4rem;
    font-size: var(--font-size-xs);
    font-weight: 600;
    color: var(--color-bg, #1a1a1a);
    background: var(--color-accent, #c8a44e);
    border-radius: 0.25rem;
    vertical-align: middle;
  }

  .schedule-note {
    margin-top: 0.75rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    max-width: 28rem;
  }
</style>
