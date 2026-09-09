<script lang="ts">
  import type { EventQualifierRace } from "$lib/api";
  import { formatTime } from "$lib/highlights";
  import { formatEventDate, ordinal, timeRemaining } from "$lib/events";

  /**
   * With `entry` null the card is a placeholder for a seed slot that has no
   * race yet (before the qualifier opens, or a voided seed): same geometry,
   * grey dashed route line, no link. `index` names the slot in both cases;
   * `opensAt` is the qualifier start while it is still ahead.
   */
  let {
    entry,
    index,
    modeLabel,
    partner,
    now,
    opensAt = null,
  }: {
    entry: EventQualifierRace | null;
    index: number;
    modeLabel: string;
    partner: string | null;
    now: Date;
    opensAt?: string | null;
  } = $props();

  let race = $derived(entry?.race ?? null);
  let mine = $derived(entry?.my_result ?? null);
  let done = $derived(mine?.status === "done");
  let finished = $derived(done && mine?.finished === true);
  let dnf = $derived(done && !finished);
  let playing = $derived(mine?.status === "playing");
  let joined = $derived(mine?.status === "joined");
  let remaining = $derived(timeRemaining(entry?.closes_at ?? null, now));
  let closed = $derived(remaining === "closed");
  let canPlay = $derived(
    !done && !playing && !joined && !closed && race?.can_join === true,
  );
  let previews = $derived(race?.participant_previews.slice(0, 5) ?? []);
  let overflow = $derived(
    Math.max(0, (race?.participant_count ?? 0) - previews.length),
  );
  // A scored DNF validated the seed (it holds a rank and points), so it rides
  // the done colour like a finished run; a DNF that never scored (fewer than
  // two zone entries) is spent: nothing ridden, nothing left to ride.
  let scored = $derived(done && mine?.points != null);
  let routeClass = $derived(
    finished || scored
      ? "route-done"
      : done
        ? "route-spent"
        : closed
          ? "route-finished"
          : "route-running",
  );
</script>

{#if race === null}
  <div class="seed-card placeholder">
    <div class="route route-setup" aria-hidden="true">
      <span class="line"></span>
      <span class="m-start"></span>
      <span class="m-end"></span>
    </div>
    <div class="inner">
      <div class="content">
        <div class="head">
          <span class="name">{modeLabel} &middot; Seed {index}</span>
          <span class="signal signal-setup"
            >{opensAt ? "Upcoming" : "Unavailable"}</span
          >
        </div>
        <div class="crew">
          <span class="remaining"
            >{opensAt ? `Opens ${formatEventDate(opensAt)}` : "No seed"}</span
          >
        </div>
        <div class="foot">
          <span class="meta"
            >{opensAt ? "Pack released at the opening" : "Seed withdrawn"}</span
          >
          <span class="byline">SpeedFog{partner ? ` × ${partner}` : ""}</span>
        </div>
      </div>
    </div>
  </div>
{:else}
  <a href="/race/{race.id}" class="seed-card {routeClass}">
    <div class="route {routeClass}" aria-hidden="true">
      <span class="line"></span>
      <span class="m-start"></span>
      <span class="m-end"></span>
      {#if routeClass === "route-running"}<span class="m-train"></span>{/if}
    </div>
    <div class="inner">
      <div class="content">
        <div class="head">
          <span class="name">{modeLabel} &middot; Seed {index}</span>
          {#if finished}
            <span class="signal signal-open">Done</span>
          {:else if dnf}
            <span class="signal signal-abandoned">DNF</span>
          {:else if playing}
            <span class="signal signal-playing">Playing</span>
          {:else if joined}
            <span class="signal signal-registered">Joined</span>
          {:else if closed}
            <span class="signal signal-finished">Closed</span>
          {:else}
            <span class="signal signal-running">Open</span>
          {/if}
        </div>
        <div class="crew">
          <div class="avatar-stack">
            {#each previews as user (user.id)}
              {#if user.twitch_avatar_url}
                <img src={user.twitch_avatar_url} alt="" class="avatar" />
              {:else}
                <span class="avatar avatar-placeholder">
                  {(user.twitch_display_name || user.twitch_username)
                    .charAt(0)
                    .toUpperCase()}
                </span>
              {/if}
            {/each}
            {#if overflow > 0}<span class="avatar avatar-placeholder"
                >+{overflow}</span
              >{/if}
          </div>
          <span class="remaining">{remaining}</span>
        </div>
        <div class="foot">
          <span class="meta"
            >{race.participant_count} player{race.participant_count === 1
              ? ""
              : "s"}</span
          >
          <span class="byline">SpeedFog{partner ? ` × ${partner}` : ""}</span>
        </div>
        {#if done && mine}
          <div class="result" class:unscored={!finished && !scored}>
            Your run: {dnf
              ? "DNF"
              : mine.rank
                ? ordinal(mine.rank)
                : "Finished"}
            {#if dnf && mine.rank}&middot; {ordinal(mine.rank)}{/if}
            {#if mine.igt_ms !== null}&middot; {formatTime(mine.igt_ms)}{/if}
            {#if mine.points !== null}&middot; {mine.points} pts{mine.provisional
                ? " provisional"
                : ""}{/if}
          </div>
        {/if}
      </div>
      {#if canPlay}
        <div class="play-strip"><span>Play</span></div>
      {/if}
    </div>
  </a>
{/if}

<style>
  .seed-card {
    position: relative;
    display: flex;
    flex-direction: column;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    color: inherit;
    text-decoration: none;
    min-width: 0;
    transition: border-color var(--transition);
  }
  .seed-card > :global(.route) {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
  }
  /* Hover takes the route line's own hue (the root carries the route state
   * class), as race cards do. */
  a.seed-card:hover {
    border-color: var(--route-color, var(--color-purple));
    border-top-color: transparent;
  }
  .seed-card.placeholder .name,
  .seed-card.placeholder .remaining {
    color: var(--color-text-secondary);
  }
  .seed-card.placeholder .meta {
    color: var(--color-text-disabled);
  }
  .inner {
    display: flex;
    flex: 1;
    min-width: 0;
  }
  .content {
    flex: 1;
    min-width: 0;
    padding: 0.8rem 1.1rem 0.9rem;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.75rem;
  }
  .name {
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .crew {
    display: flex;
    align-items: center;
    gap: 1rem;
    margin-top: 0.75rem;
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
  .avatar-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface-elevated);
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    font-weight: 600;
  }
  .remaining {
    margin-left: auto;
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    white-space: nowrap;
  }
  .foot {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    margin-top: 0.6rem;
  }
  .meta {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }
  .byline {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }
  .result {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-success);
    margin-top: 0.3rem;
  }
  .result.unscored {
    color: var(--color-text-secondary);
  }
  .play-strip {
    width: 64px;
    background: rgba(74, 174, 140, 0.12);
    border-left: 1px solid rgba(74, 174, 140, 0.25);
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
  }
  .play-strip span {
    color: var(--color-success);
    font-family: var(--font-display);
    font-weight: 600;
    font-size: var(--font-size-base);
    text-transform: uppercase;
    letter-spacing: 0.1em;
  }
</style>
