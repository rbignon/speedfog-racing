<script lang="ts">
  import type { Race } from "$lib/api";
  import { goto } from "$app/navigation";
  import { raceDisplayDate } from "$lib/utils/time";
  import { formatPoolName } from "$lib/utils/format";
  import { isFrogTitle, statusLabel } from "$lib/format";

  let {
    race,
    role,
    variant = "default",
  }: {
    race: Race;
    role?: string;
    variant?: "default" | "compact";
  } = $props();

  let isRunning = $derived(race.status === "running");
  let isFrog = $derived(isFrogTitle(race.name));
  let displayName = $derived(
    race.organizer.twitch_display_name || race.organizer.twitch_username,
  );
  let overflowCount = $derived(
    Math.max(0, race.participant_count - race.participant_previews.length),
  );
  let winner = $derived(
    race.status === "finished" && race.participant_previews[0]?.placement === 1
      ? race.participant_previews[0]
      : null,
  );

  const roleLabels: Record<string, string> = {
    organizing: "Organizing",
    participating: "Participating",
    casting: "Casting",
  };
  let effectiveRole = $derived(
    role ?? (race.my_role ? roleLabels[race.my_role] : undefined),
  );
  let relativeTime = $derived(
    race.started_at || (race.scheduled_at && race.status === "setup")
      ? raceDisplayDate(race)
      : "TBD",
  );
  let showOpenBadge = $derived(
    (race.open_registration && race.status === "setup") ||
      (race.status === "running" && race.can_join),
  );
  let routeState = $derived(
    race.status === "finished"
      ? "finished"
      : race.status === "running"
        ? "running"
        : race.open_registration
          ? "open"
          : "setup",
  );
</script>

<a
  href="/race/{race.id}"
  class="race-card"
  class:compact={variant === "compact"}
  class:joinable={race.can_join}
>
  <div class="route route-{routeState}" aria-hidden="true">
    <span class="line"></span>
    <span class="m-start"></span>
    {#if routeState !== "setup"}
      <span class="m-end"></span>
    {/if}
    {#if isRunning}
      <span class="m-train"></span>
    {/if}
  </div>
  <div class="card-inner">
    <div class="card-content">
      <div class="race-header">
        <div class="race-title">
          {#if isFrog}
            <img src="/badges/frog.svg" alt="" class="frog-icon" />
          {/if}
          <span class="race-name" class:frog={isFrog}>{race.name}</span>
        </div>
        <div class="race-signals">
          {#if showOpenBadge}
            <span class="signal signal-open">Open</span>
          {/if}
          {#if effectiveRole}
            <span class="chip">{effectiveRole}</span>
          {/if}
          <span class="signal signal-{race.status}"
            >{statusLabel(race.status)}</span
          >
        </div>
      </div>

      <div class="race-meta">
        {race.participant_count}{#if race.max_participants && race.status == "setup"}/{race.max_participants}{/if}
        player{race.participant_count !== 1 ? "s" : ""}
        {#if race.pool_name}
          &middot; {formatPoolName(race.pool_name)}
        {/if}
      </div>

      {#if isRunning && race.casters.length > 0}
        <div class="caster-row">
          <svg
            class="twitch-icon"
            viewBox="0 0 24 24"
            fill="currentColor"
            width="14"
            height="14"
          >
            <path
              d="M11.571 4.714h1.715v5.143H11.57zm4.715 0H18v5.143h-1.714zM6 0L1.714 4.286v15.428h5.143V24l4.286-4.286h3.428L22.286 12V0zm14.571 11.143l-3.428 3.428h-3.429l-3 3v-3H6.857V1.714h13.714z"
            />
          </svg>
          {#each race.casters as caster, i}
            {#if i > 0}<span class="caster-sep">&middot;</span>{/if}
            <button
              class="caster-name"
              onclick={(e: MouseEvent) => {
                e.preventDefault();
                e.stopPropagation();
                window.open(
                  `https://twitch.tv/${caster.user.twitch_username}`,
                  "_blank",
                  "noopener,noreferrer",
                );
              }}
              >{caster.user.twitch_display_name ||
                caster.user.twitch_username}</button
            >
          {/each}
        </div>
      {/if}

      <div class="card-foot" class:has-winner={winner}>
        <div class="crew">
          {#if race.participant_previews.length > 0}
            <div class="avatar-stack">
              {#each race.participant_previews as user}
                {#if user.twitch_avatar_url}
                  <img
                    src={user.twitch_avatar_url}
                    alt={user.twitch_display_name || user.twitch_username}
                    class="avatar"
                  />
                {:else}
                  <span class="avatar avatar-placeholder">
                    {(user.twitch_display_name || user.twitch_username)
                      .charAt(0)
                      .toUpperCase()}
                  </span>
                {/if}
              {/each}
              {#if overflowCount > 0}
                <span class="avatar avatar-overflow">+{overflowCount}</span>
              {/if}
            </div>
            {#if winner}
              <span class="winner-info">
                <span class="place">1st</span>
                {#if winner.twitch_avatar_url}
                  <img
                    src={winner.twitch_avatar_url}
                    alt=""
                    class="winner-avatar"
                  />
                {/if}
                <span class="winner-name"
                  >{winner.twitch_display_name || winner.twitch_username}</span
                >
              </span>
            {:else if race.status === "finished"}
              <span class="no-finishers">No finishers</span>
            {/if}
          {:else}
            <span class="no-participants">No players yet</span>
          {/if}
        </div>
        <span class="byline">
          by
          {#if race.organizer.twitch_avatar_url}
            <img
              src={race.organizer.twitch_avatar_url}
              alt=""
              class="organizer-avatar"
            />
          {/if}
          <button
            class="organizer-link"
            onclick={(e) => {
              e.preventDefault();
              e.stopPropagation();
              goto(`/user/${race.organizer.twitch_username}`);
            }}
          >
            {displayName}
          </button>
          <span class="ago">&middot; {relativeTime}</span>
        </span>
      </div>
      {#if race.status === "running" && race.open_registration && race.registration_closes_at && new Date(race.registration_closes_at) > new Date()}
        <div class="late-join-note">
          Joinable until {new Date(
            race.registration_closes_at,
          ).toLocaleTimeString([], {
            hour: "2-digit",
            minute: "2-digit",
            hour12: false,
          })}
        </div>
      {/if}
    </div>
    {#if race.can_join}
      <div class="join-strip">
        <span class="join-strip-text">Join</span>
      </div>
    {/if}
  </div>
</a>

<style>
  .race-card {
    position: relative;
    display: block;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 0;
    text-decoration: none;
    color: inherit;
    min-width: 0;
    transition: border-color var(--transition);
  }

  /* The route rides the card's real top border; the negative side offsets
   * pull the line's 14px insets back so it spans nearly the whole border,
   * markers sitting just inside the corners and straddling the edge. */
  .race-card > :global(.route) {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
  }

  .race-card:hover {
    border-color: var(--color-purple);
  }

  .card-inner {
    min-width: 0;
  }

  .joinable .card-inner {
    display: flex;
  }

  .card-content {
    min-width: 0;
    flex: 1;
    padding: 0.8rem 1.1rem 0.9rem;
  }

  .compact .card-content {
    padding: 0.6rem 0.9rem 0.7rem;
  }

  /* Header row */
  .race-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.75rem;
  }

  .race-title {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    min-width: 0;
  }

  .race-name {
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .race-name.frog {
    color: #3e9e5c;
  }

  .frog-icon {
    width: 1.1rem;
    height: 1.1rem;
    flex-shrink: 0;
  }

  .race-signals {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    flex-shrink: 0;
  }

  /* Meta row */
  .race-meta {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    margin-top: 0.1rem;
  }

  /* Caster row */
  .caster-row {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: var(--font-size-xs);
    color: var(--color-twitch, #9146ff);
    margin-top: 0.5rem;
    overflow: hidden;
    white-space: nowrap;
    text-overflow: ellipsis;
  }

  .twitch-icon {
    flex-shrink: 0;
    width: 12px;
    height: 12px;
  }

  .caster-sep {
    color: var(--color-text-disabled);
  }

  .caster-name {
    background: none;
    border: none;
    padding: 0;
    font: inherit;
    color: var(--color-twitch, #9146ff);
    cursor: pointer;
  }

  .caster-name:hover {
    text-decoration: underline;
  }

  /* Foot row: crew + winner on the left, byline on the right */
  .card-foot {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    margin-top: 0.8rem;
  }

  .crew {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    min-width: 0;
  }

  .avatar-stack {
    display: flex;
    align-items: center;
  }

  .avatar {
    width: 26px;
    height: 26px;
    border-radius: 50%;
    border: 2px solid var(--color-surface);
    margin-left: -6px;
    object-fit: cover;
  }

  .avatar:first-child {
    margin-left: 0;
  }

  .avatar-placeholder,
  .avatar-overflow {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface-elevated);
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }

  .no-participants {
    font-size: var(--font-size-sm);
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .no-finishers {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    white-space: nowrap;
  }

  .winner-info {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
    overflow: hidden;
  }

  .winner-info .place {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--color-gold);
    flex-shrink: 0;
  }

  .winner-avatar {
    width: 20px;
    height: 20px;
    border-radius: 50%;
    object-fit: cover;
  }

  .winner-name {
    font-weight: 600;
    font-size: var(--font-size-sm);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .byline {
    display: flex;
    align-items: center;
    gap: 0.35rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    flex-shrink: 0;
  }

  .organizer-avatar {
    width: 18px;
    height: 18px;
    border-radius: 50%;
  }

  .organizer-link {
    background: none;
    border: none;
    padding: 0;
    color: inherit;
    font: inherit;
    cursor: pointer;
  }

  .organizer-link:hover {
    color: var(--color-purple);
  }

  .ago {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .late-join-note {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    margin-top: 0.25rem;
  }

  /* Joinable card layout */
  .join-strip {
    width: 64px;
    background: rgba(74, 174, 140, 0.12);
    border-left: 1px solid rgba(74, 174, 140, 0.25);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }

  .join-strip-text {
    color: var(--color-success);
    font-family: var(--font-display);
    font-weight: 600;
    font-size: var(--font-size-base);
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }

  @media (max-width: 640px) {
    .card-foot.has-winner .crew {
      flex-wrap: wrap;
    }

    .card-foot.has-winner .winner-info {
      order: -1;
      width: 100%;
      margin-bottom: 0.35rem;
    }
  }
</style>
