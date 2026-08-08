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
  import { rewards } from "$lib/stores/rewards.svelte";
  import ActivityList from "$lib/components/ActivityList.svelte";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
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
              <span class="chip">admin</span>
            {/if}
            {#if profile.stats.organized_count > 0}
              <span class="chip">organizer</span>
            {/if}
            {#if profile.stats.casted_count > 0}
              <span class="chip">caster</span>
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
    </div>

    <UserStatsCards {profile} streakDisplay="best" />

    {#if traits}
      <section class="play-style-section">
        <SectionTitle>Play Style</SectionTitle>
        <PlayStyle {traits} />
      </section>
    {/if}

    {#if poolStats && poolStats.pools.length > 0}
      <section class="mode-stats-section">
        <SectionTitle>Mode Stats</SectionTitle>
        <ModeStats pools={poolStats.pools} />
      </section>
    {/if}

    {#if activity}
      <section class="activity-section">
        <SectionTitle>Activity</SectionTitle>
        {#if activity.items.length === 0}
          <p class="empty">No activity yet.</p>
        {:else}
          <ActivityList items={activity.items} formatDate={formatFullDate} />

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
    font-size: 1.9rem;
    font-weight: 700;
    color: var(--color-text);
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

  .empty {
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .load-more {
    margin-top: 1rem;
    width: 100%;
  }

  @media (max-width: 640px) {
    .profile-page {
      padding: 1rem;
    }
  }
</style>
