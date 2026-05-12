<script lang="ts">
  import { page } from "$app/state";
  import {
    fetchUserProfile,
    fetchUserActivity,
    fetchUserPoolStats,
    fetchUserTraits,
    type UserProfile,
    type UserPoolStats,
    type ActivityTimeline,
    type UserTraitsResponse,
  } from "$lib/api";
  import { statusLabel } from "$lib/format";
  import { formatPoolName } from "$lib/utils/format";
  import { formatIgt } from "$lib/utils/training";
  import { rewards } from "$lib/stores/rewards.svelte";
  import UserStatsCards from "$lib/components/UserStatsCards.svelte";
  import ModeStats from "$lib/components/ModeStats.svelte";
  import PlayStyle from "$lib/components/PlayStyle.svelte";

  let username = $derived(page.params.username!);
  let profile = $state<UserProfile | null>(null);
  let poolStats = $state<UserPoolStats | null>(null);
  let activity = $state<ActivityTimeline | null>(null);
  let traits = $state<UserTraitsResponse | null>(null);
  let loading = $state(true);
  let loadingMore = $state(false);
  let error = $state<string | null>(null);

  let phantomSkin = $derived(
    rewards.lookupPhantomSkin(profile?.equipped_phantom_skin_id),
  );
  let useSkinAsAvatar = $derived(
    phantomSkin !== null && phantomSkin.id !== "none",
  );

  let nameStyle = $derived.by(() => {
    const id = profile?.equipped_name_template_id;
    if (!id || id === "default") return "";
    const t = rewards.lookupTemplate(id);
    if (!t) return "";
    const parts: string[] = [];
    if (t.gradient) {
      parts.push(
        `background: linear-gradient(90deg, ${t.gradient[0]}, ${t.gradient[1]});`,
        "-webkit-background-clip: text;",
        "background-clip: text;",
        "color: transparent;",
        "padding-inline-end: 0.1em;",
      );
    } else if (t.color) {
      parts.push(`color: ${t.color};`);
    }
    if (t.name_css) {
      parts.push(t.name_css);
    }
    return parts.join(" ");
  });

  $effect(() => {
    loadProfile();
  });

  async function loadProfile() {
    loading = true;
    error = null;
    try {
      const [p, a, ps, t] = await Promise.all([
        fetchUserProfile(username),
        fetchUserActivity(username),
        fetchUserPoolStats(username),
        fetchUserTraits(username).catch(() => null),
        rewards.ensureLoaded().catch(() => undefined),
      ]);
      profile = p;
      activity = a;
      poolStats = ps;
      traits = t;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load profile.";
    } finally {
      loading = false;
    }
  }

  async function loadMore() {
    if (!activity || !activity.has_more) return;
    loadingMore = true;
    try {
      const more = await fetchUserActivity(username, activity.items.length);
      activity = {
        items: [...activity.items, ...more.items],
        total: more.total,
        has_more: more.has_more,
      };
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load more activity.";
    } finally {
      loadingMore = false;
    }
  }

  function formatDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
  }

  function formatFullDate(dateStr: string): string {
    return new Date(dateStr).toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
    });
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
</script>

<svelte:head>
  <title>
    {profile
      ? profile.twitch_display_name || profile.twitch_username
      : "Profile"} - SpeedFog Racing
  </title>
</svelte:head>

<main class="profile-page">
  {#if loading}
    <p class="loading">Loading profile...</p>
  {:else if error && !profile}
    <div class="error-state">
      <p>{error}</p>
      <a href="/" class="btn btn-secondary">Home</a>
    </div>
  {:else if profile}
    <div class="profile-header">
      <div class="profile-identity">
        {#if useSkinAsAvatar && phantomSkin}
          <img
            src="/phantom_skins/{phantomSkin.id}-avatar.jpg"
            alt={phantomSkin.name}
            class="profile-avatar"
          />
        {:else if profile.twitch_avatar_url}
          <img src={profile.twitch_avatar_url} alt="" class="profile-avatar" />
        {:else}
          <div class="profile-avatar-placeholder"></div>
        {/if}
        <div class="profile-info">
          <div class="profile-name-row">
            <h1>
              <span style={nameStyle}
                >{profile.twitch_display_name || profile.twitch_username}</span
              >
            </h1>
            <a
              href="https://twitch.tv/{profile.twitch_username}"
              target="_blank"
              rel="noopener noreferrer"
              class="twitch-link"
              title="Twitch channel"
              aria-label="Twitch channel"
            >
              <svg
                viewBox="0 0 24 24"
                width="18"
                height="18"
                fill="currentColor"
              >
                <path
                  d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714Z"
                />
              </svg>
            </a>
            {#if profile.role === "admin"}
              <span class="role-badge admin">admin</span>
            {/if}
            {#if profile.stats.organized_count > 0}
              <span class="role-badge organizer">organizer</span>
            {/if}
            {#if profile.stats.casted_count > 0}
              <span class="role-badge caster">caster</span>
            {/if}
          </div>
          <p class="profile-joined">
            <span>Joined {formatDate(profile.created_at)}</span>
            {#if profile.held_badges && profile.held_badges.length > 0}
              {#each profile.held_badges as badge (badge.id)}
                <span
                  class="profile-badge"
                  title={badge.description ?? badge.name}
                >
                  <img
                    src="/badges/{badge.icon_filename}"
                    alt=""
                    class="profile-badge-icon"
                  />
                  <span>{badge.name}</span>
                </span>
              {/each}
            {/if}
          </p>
        </div>
      </div>
      {#if traits}
        <a
          href="/stats?tab=leaderboard"
          class="elo-block"
          title="View leaderboard"
        >
          {#if traits.elo_rank}
            <span class="elo-rank">#{traits.elo_rank}</span>
          {/if}
          <span class="elo-value">{traits.elo_rating}</span>
          <span class="elo-label">ELO</span>
          {#if traits.elo_trend_delta !== 0}
            <span
              class="elo-trend"
              class:elo-trend-up={traits.elo_trend_delta > 0}
              class:elo-trend-down={traits.elo_trend_delta < 0}
            >
              {traits.elo_trend_delta > 0 ? "+" : ""}{traits.elo_trend_delta}
            </span>
          {/if}
        </a>
      {/if}
    </div>

    <UserStatsCards {profile} streakDisplay="best" />

    {#if traits}
      <section class="play-style-section">
        <h2>Play Style</h2>
        <PlayStyle {traits} />
      </section>
    {/if}

    {#if poolStats && poolStats.pools.length > 0}
      <section class="mode-stats-section">
        <h2>Mode Stats</h2>
        <ModeStats pools={poolStats.pools} />
      </section>
    {/if}

    {#if activity}
      <section class="activity-section">
        <h2>Activity</h2>
        {#if activity.items.length === 0}
          <p class="empty">No activity yet.</p>
        {:else}
          <div class="timeline">
            {#each activity.items as item (item.type + "-" + ("race_id" in item ? item.race_id : "session_id" in item ? item.session_id : "") + "-" + item.date)}
              <div class="activity-card">
                <span class="activity-date">{formatFullDate(item.date)}</span>
                {#if item.type === "race_participant"}
                  <div class="activity-body">
                    <div class="badge-row">
                      <span class="activity-badge participant">Race</span>
                      {#if item.is_organizer}
                        <span class="activity-badge organizer">Organized</span>
                      {/if}
                      <span class="badge badge-{item.status}"
                        >{statusLabel(item.status)}</span
                      >
                    </div>
                    <a href="/race/{item.race_id}" class="activity-title">
                      {item.race_name}
                    </a>
                    <div class="activity-details">
                      {#if item.placement}
                        <span
                          class="placement {placementClass(item.placement)}"
                        >
                          {placementLabel(item.placement)} / {item.total_starters}
                        </span>
                      {:else if item.status === "finished"}
                        <span class="placement-dnf"
                          >DNF / {item.total_starters}</span
                        >
                      {/if}
                      <span class="mono">{formatIgt(item.igt_ms)}</span>
                      <span>{item.death_count} deaths</span>
                    </div>
                  </div>
                {:else if item.type === "race_organizer"}
                  <div class="activity-body">
                    <div class="badge-row">
                      <span class="activity-badge organizer">Organized</span>
                      <span class="badge badge-{item.status}"
                        >{statusLabel(item.status)}</span
                      >
                    </div>
                    <a href="/race/{item.race_id}" class="activity-title">
                      {item.race_name}
                    </a>
                    <div class="activity-details">
                      <span>{item.participant_count} players</span>
                    </div>
                  </div>
                {:else if item.type === "race_caster"}
                  <div class="activity-body">
                    <div class="badge-row">
                      <span class="activity-badge caster">Casted</span>
                      <span class="badge badge-{item.status}"
                        >{statusLabel(item.status)}</span
                      >
                    </div>
                    <a href="/race/{item.race_id}" class="activity-title">
                      {item.race_name}
                    </a>
                  </div>
                {:else if item.type === "training"}
                  <div class="activity-body">
                    <div class="badge-row">
                      <span class="activity-badge training">Solo</span>
                      <span class="badge badge-{item.status}"
                        >{statusLabel(item.status)}</span
                      >
                      {#if item.exclude_from_stats}
                        <span class="badge badge-slow">Slow</span>
                      {/if}
                    </div>
                    <a
                      href="/training/{item.session_id}"
                      class="activity-title"
                    >
                      {item.pool_display_name || formatPoolName(item.pool_name)}
                    </a>
                    <div class="activity-details">
                      <span class="mono">{formatIgt(item.igt_ms)}</span>
                      <span>{item.death_count} deaths</span>
                    </div>
                  </div>
                {:else if item.type === "daily_participant"}
                  <div class="activity-body">
                    <div class="badge-row">
                      <span class="activity-badge daily">Daily</span>
                      {#if item.status === "running"}
                        <span class="activity-badge daily-active">Active</span>
                      {/if}
                    </div>
                    <a href="/daily/{item.daily_date}" class="activity-title">
                      {item.pool_display_name || formatPoolName(item.pool_name)}
                    </a>
                    <div class="activity-details">
                      {#if item.placement}
                        <span
                          class="placement {placementClass(item.placement)}"
                        >
                          {placementLabel(item.placement)} / {item.total_starters}
                        </span>
                      {:else if item.status === "finished"}
                        <span class="placement-dnf"
                          >DNF / {item.total_starters}</span
                        >
                      {/if}
                      <span class="mono">{formatIgt(item.igt_ms)}</span>
                      <span>{item.death_count} deaths</span>
                    </div>
                  </div>
                {/if}
              </div>
            {/each}
          </div>

          {#if activity.has_more}
            <button
              class="btn btn-secondary load-more"
              disabled={loadingMore}
              onclick={loadMore}
            >
              {loadingMore ? "Loading..." : "Load more"}
            </button>
          {/if}
        {/if}
      </section>
    {/if}
  {/if}
</main>

<style>
  .profile-page {
    width: 100%;
    max-width: 800px;
    margin: 0 auto;
    padding: 2rem;
    box-sizing: border-box;
  }

  .loading {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .error-state {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 1rem;
    padding: 3rem;
    color: var(--color-text-secondary);
  }

  .profile-header {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 1.25rem;
    margin-bottom: 2rem;
  }

  .profile-identity {
    display: flex;
    align-items: center;
    gap: 1.25rem;
    min-width: 0;
  }

  .elo-block {
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.1rem;
    flex-shrink: 0;
    text-decoration: none;
    color: inherit;
    transition: opacity var(--transition);
  }

  .elo-block:hover {
    opacity: 0.8;
  }

  .elo-rank {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    font-variant-numeric: tabular-nums;
  }

  .elo-value {
    font-size: var(--font-size-2xl);
    font-weight: 700;
    font-variant-numeric: tabular-nums;
    line-height: 1;
  }

  .elo-label {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .elo-trend {
    font-size: var(--font-size-sm);
    font-weight: 600;
    font-variant-numeric: tabular-nums;
  }

  .elo-trend-up {
    color: #10b981;
  }

  .elo-trend-down {
    color: #ef4444;
  }

  .profile-avatar {
    width: 72px;
    height: 72px;
    border-radius: 50%;
    object-fit: cover;
    border: 2px solid var(--color-border);
  }

  .profile-avatar-placeholder {
    width: 72px;
    height: 72px;
    border-radius: 50%;
    background: var(--color-surface);
    border: 2px solid var(--color-border);
  }

  .profile-info {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
  }

  .profile-name-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .profile-name-row h1 {
    margin: 0;
    font-size: var(--font-size-2xl);
    font-weight: 700;
    color: var(--color-gold);
  }

  .role-badge {
    font-size: var(--font-size-xs);
    padding: 0.15rem 0.5rem;
    border-radius: var(--radius-sm);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
  }

  .role-badge.organizer {
    background: rgba(168, 85, 247, 0.15);
    color: var(--color-purple);
  }

  .role-badge.caster {
    background: rgba(59, 130, 246, 0.15);
    color: var(--color-info);
  }

  .role-badge.admin {
    background: rgba(239, 68, 68, 0.15);
    color: var(--color-danger);
  }

  .profile-joined {
    margin: 0;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    display: flex;
    flex-wrap: wrap;
    align-items: center;
    gap: 0.25rem 0.75rem;
  }

  .profile-badge {
    display: inline-flex;
    align-items: center;
    gap: 0.3rem;
  }

  .profile-badge-icon {
    width: 18px;
    height: 18px;
    flex-shrink: 0;
  }

  .twitch-link {
    color: var(--color-text-secondary);
    display: flex;
    align-items: center;
    transition: color var(--transition);
  }

  .twitch-link:hover {
    color: var(--color-purple);
  }

  .play-style-section,
  .mode-stats-section {
    margin-bottom: 2.5rem;
  }

  .play-style-section h2,
  .mode-stats-section h2,
  .activity-section h2 {
    font-size: var(--font-size-lg);
    font-weight: 600;
    margin: 0 0 1rem 0;
    color: var(--color-gold);
  }

  .empty {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .timeline {
    display: flex;
    flex-direction: column;
    gap: 0.5rem;
  }

  .activity-card {
    display: flex;
    align-items: flex-start;
    gap: 1rem;
    padding: 0.75rem 1rem;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
  }

  .activity-date {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    white-space: nowrap;
    min-width: 6rem;
    padding-top: 0.15rem;
  }

  .activity-body {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    flex: 1;
  }

  .activity-badge {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.1rem 0.4rem;
    border-radius: var(--radius-sm);
    width: fit-content;
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
    background: rgba(139, 92, 246, 0.15);
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

  .badge-row {
    display: flex;
    align-items: center;
    gap: 0.4rem;
  }

  .activity-title {
    color: var(--color-text);
    text-decoration: none;
    font-weight: 600;
  }

  .activity-title:hover {
    color: var(--color-purple);
    text-decoration: underline;
  }

  .activity-details {
    display: flex;
    gap: 0.75rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
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

  .placement-dnf {
    font-weight: 600;
    color: var(--color-text-disabled);
  }

  .mono {
    font-variant-numeric: tabular-nums;
  }

  .load-more {
    margin-top: 1rem;
    width: 100%;
  }

  @media (max-width: 640px) {
    .profile-page {
      padding: 1rem;
    }

    .activity-card {
      flex-direction: column;
      gap: 0.25rem;
    }

    .activity-date {
      min-width: auto;
    }
  }
</style>
