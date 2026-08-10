<script lang="ts">
  import type { Race } from "$lib/api";
  import { goto } from "$app/navigation";
  import { raceDisplayDate } from "$lib/utils/time";
  import { formatPoolName } from "$lib/utils/format";
  import { isFrogTitle, statusLabel } from "$lib/format";

  let {
    race,
    variant = "default",
  }: {
    race: Race;
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
  let roleLabel = $derived(race.my_role ? roleLabels[race.my_role] : undefined);
  let relativeTime = $derived(
    race.started_at || (race.scheduled_at && race.status === "setup")
      ? raceDisplayDate(race)
      : "TBD",
  );
  let showOpenBadge = $derived(
    (race.open_registration && race.status === "setup") ||
      (race.status === "running" && race.can_join),
  );
  /* The route line reads from the viewer's seat (see the route vocabulary
   * in app.css): grey dashes while the race is in setup, ember with the
   * traveling dot when it runs without them, their brass progress while
   * they ride (from registration on), verdigris once they finished, steel
   * when the race is over. */
  let myProgress = $derived(
    race.my_current_layer != null && race.seed_total_layers
      ? Math.min(1, race.my_current_layer / race.seed_total_layers)
      : 0,
  );
  let routeView = $derived.by(() => {
    const mine = race.my_participant_status != null;
    if (race.status === "finished")
      return { classes: "route-finished", progress: null as number | null };
    if (race.status === "running") {
      if (!mine) return { classes: "route-running", progress: null };
      if (race.my_participant_status === "finished")
        return { classes: "route-done", progress: null };
      return { classes: "route-progress", progress: myProgress };
    }
    return {
      classes: mine ? "route-setup route-progress" : "route-setup",
      progress: mine ? myProgress : null,
    };
  });
</script>

<a
  href="/race/{race.id}"
  class="race-card {routeView.classes}"
  class:compact={variant === "compact"}
  class:joinable={race.can_join}
>
  <div
    class="route {routeView.classes}"
    style={routeView.progress != null
      ? `--route-progress: ${routeView.progress}`
      : null}
    aria-hidden="true"
  >
    <span class="line"></span>
    {#if routeView.progress != null}
      <span class="line-progress"></span>
      <span class="m-pos"></span>
    {/if}
    <span class="m-start"></span>
    <span class="m-end"></span>
    {#if routeView.classes === "route-running"}
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
          {#if roleLabel}
            <span class="signal signal-{race.my_role}">{roleLabel}</span>
          {/if}
          <span class="signal signal-{race.status}"
            >{statusLabel(race.status)}</span
          >
        </div>
      </div>

      <div class="card-crew" class:has-winner={winner}>
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
          {:else}
            <span class="no-participants">No players yet</span>
          {/if}
        </div>
        {#if winner}
          <span class="winner-info">
            {#if winner.twitch_avatar_url}
              <img
                src={winner.twitch_avatar_url}
                alt="Winner"
                class="winner-avatar"
              />
            {:else}
              <span class="place">1st</span>
            {/if}
            <span class="winner-name"
              >{winner.twitch_display_name || winner.twitch_username}</span
            >
          </span>
        {:else if race.status === "finished"}
          <span class="no-finishers">No finishers</span>
        {/if}
        <span class="ago">{relativeTime}</span>
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

      <div class="card-foot">
        <div class="race-meta">
          {race.participant_count}{#if race.max_participants && race.status == "setup"}/{race.max_participants}{/if}
          player{race.participant_count !== 1 ? "s" : ""}
          {#if race.pool_name}
            &middot; {formatPoolName(race.pool_name)}
          {/if}
          {#if race.deathless}
            {#if !race.pool_name}&middot;{/if}
            <span class="deathless" title="Dying once eliminates you"
              >Deathless</span
            >
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
    /* The route line IS the top edge: the border under it stays
     * transparent so dashes never sit on a second stroke. */
    border-top-color: transparent;
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

  /* Hover highlights in the route line's own hue (set by the root's
   * route state classes), tying the affordance to the card's status. */
  .race-card:hover {
    border-color: var(--route-color, var(--color-purple));
    border-top-color: transparent;
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
    color: #5cb168;
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

  /* Meta: player count + mode, in the foot row */
  .race-meta {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    min-width: 0;
  }

  /* Same mono ember micro-label as the daily timetable's deathless tag */
  .race-meta .deathless {
    display: inline-block;
    margin-left: 0.3rem;
    font-size: 0.6rem;
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-danger);
    cursor: default;
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

  /* Crew row: avatars on the left, winner in the middle, date on the right */
  .card-crew {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-top: 0.75rem;
  }

  /* Foot row: players + mode on the left, organizer on the right */
  .card-foot {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    margin-top: 0.6rem;
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
    flex: 1;
    text-align: center;
    font-family: var(--font-mono);
    font-size: 0.7rem;
    letter-spacing: 0.07em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    white-space: nowrap;
  }

  .winner-info {
    flex: 1;
    display: flex;
    align-items: center;
    justify-content: center;
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

  /* The brass ring IS the winner mark next to an avatar; the mono 1st
   * tag only steps in when the winner has no avatar to ring. */
  .winner-avatar {
    width: 22px;
    height: 22px;
    border: 2px solid var(--color-gold);
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
    /* Pushes to the row's right edge even when the winner slot is empty */
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    white-space: nowrap;
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
    .card-crew.has-winner {
      flex-wrap: wrap;
    }

    .card-crew.has-winner .winner-info {
      order: -1;
      flex: 1 0 100%;
      justify-content: flex-start;
      margin-bottom: 0.35rem;
    }
  }
</style>
