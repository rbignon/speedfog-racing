<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { DailyWeekDay, DailyWeekResponse } from "$lib/api";
  import { fetchDailyWeek } from "$lib/api";
  import { cellStrip } from "$lib/daily";
  import { formatIgt } from "$lib/utils/training";
  import UserLink from "$lib/components/UserLink.svelte";

  interface Props {
    week: DailyWeekResponse;
    variant?: "home" | "dashboard" | "daily-detail";
    selectedDate?: string;
    onWeekChange?: (weekStart: string) => void;
  }

  let { week, variant = "home", selectedDate, onWeekChange }: Props = $props();

  // svelte-ignore state_referenced_locally
  let displayedWeek = $state<DailyWeekResponse>(week);
  // svelte-ignore state_referenced_locally
  let lastSeenParentWeekStart = $state<string>(week.week_start);
  let navigating = $state(false);

  // ``week`` rebinds happen for both URL nav (different ``week_start``,
  // must follow) and live WS patches (same ``week_start``, only follow
  // while the user hasn't navigated locally to a different week).
  $effect(() => {
    const incoming = week;
    untrack(() => {
      const parentMoved = incoming.week_start !== lastSeenParentWeekStart;
      lastSeenParentWeekStart = incoming.week_start;
      if (parentMoved || displayedWeek.week_start === incoming.week_start) {
        displayedWeek = incoming;
      }
    });
  });

  // Report the displayed week back to the parent (fires on mount and whenever
  // local navigation or a parent update moves the week). Lets a host page bind
  // other views, e.g. a weekly leaderboard, to the week shown in the toolbar.
  $effect(() => {
    const ws = displayedWeek.week_start;
    untrack(() => onWeekChange?.(ws));
  });

  function currentWeekMondayFor(todayIso: string): string {
    const d = new Date(`${todayIso}T00:00:00Z`);
    const weekday = (d.getUTCDay() + 6) % 7; // 0 = Monday
    return new Date(d.getTime() - weekday * 86_400_000)
      .toISOString()
      .slice(0, 10);
  }

  let canGoNext = $derived(
    displayedWeek.week_start < currentWeekMondayFor(displayedWeek.today),
  );

  async function navigate(deltaWeeks: number) {
    if (navigating) return;
    if (deltaWeeks > 0 && !canGoNext) return;
    if (deltaWeeks < 0 && !displayedWeek.has_earlier) return;
    const startMs = new Date(`${displayedWeek.week_start}T00:00:00Z`).getTime();
    const anchorDate = new Date(startMs + deltaWeeks * 7 * 86_400_000)
      .toISOString()
      .slice(0, 10);
    navigating = true;
    try {
      displayedWeek = await fetchDailyWeek(anchorDate);
    } catch {
      // swallow: the displayed week stays put.
    } finally {
      navigating = false;
    }
  }

  let now = $state(Date.now());
  // Earliest "future" started_at on the displayed week. Used to switch the
  // tick from 60s to 1s only when the next opening is within an hour, so
  // the grid does not re-render every second on the home and dashboard
  // pages where users may sit indefinitely.
  let nextOpensMs = $derived.by(() => {
    let min = Infinity;
    for (const day of displayedWeek.days) {
      if (day.state === "future" && day.started_at) {
        const t = new Date(day.started_at).getTime();
        if (t < min) min = t;
      }
    }
    return min;
  });
  $effect(() => {
    const target = nextOpensMs;
    let cancelled = false;
    let timeoutId: ReturnType<typeof setTimeout>;
    const schedule = () => {
      const remaining = target - Date.now();
      const period = remaining < 3_600_000 ? 1_000 : 60_000;
      timeoutId = setTimeout(() => {
        if (cancelled) return;
        now = Date.now();
        schedule();
      }, period);
    };
    schedule();
    return () => {
      cancelled = true;
      clearTimeout(timeoutId);
    };
  });

  const WEEKDAY_LABELS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

  function countdown(targetIso: string | null): string {
    if (!targetIso) return "";
    const target = new Date(targetIso).getTime();
    const remainingMs = Math.max(0, target - now);
    const days = Math.floor(remainingMs / 86_400_000);
    const hours = Math.floor((remainingMs % 86_400_000) / 3_600_000);
    if (days >= 1) {
      return `${days}d ${hours}h`;
    }
    const minutes = Math.floor((remainingMs % 3_600_000) / 60_000);
    if (hours >= 1) {
      return `${hours}h ${String(minutes).padStart(2, "0")}m`;
    }
    const seconds = Math.floor((remainingMs % 60_000) / 1_000);
    if (minutes >= 1) {
      return `${minutes}m ${String(seconds).padStart(2, "0")}s`;
    }
    return `${seconds}s`;
  }

  function hrefFor(day: DailyWeekDay): string | null {
    if (day.state === "today") return "/daily";
    if (day.state === "past") return `/daily/${day.date}`;
    return null;
  }

  /** The viewer finished this day's seed: their route reads in verdigris. */
  function myDone(day: DailyWeekDay): boolean {
    return day.my_result?.status === "finished";
  }

  /* The week is one continuous metro line across the plate's top: each
   * day contributes its segment, colored by what happened on it. Today
   * distinguishes "the seed is on" (ember) from "the viewer is riding it"
   * (brass, the charter's playing hue) from "ridden" (verdigris). */
  function wlClass(day: DailyWeekDay): string {
    if (myDone(day)) return "wl-done";
    if (day.state === "today") {
      const r = day.my_result;
      return r && r.status !== "abandoned" ? "wl-playing" : "wl-today";
    }
    if (day.state === "past") return "wl-closed";
    return "wl-future";
  }

  /* The terminal square fills once the week is over (time-based, not
   * participation-based: a week of missed days still closes). */
  let weekOver = $derived.by(() => {
    const last = displayedWeek.days[displayedWeek.days.length - 1];
    return last != null && last.state !== "future" && last.state !== "today";
  });

  let scrollContainer: HTMLDivElement | undefined = $state();
  onMount(() => {
    const el = scrollContainer;
    if (!el) return;
    const target =
      (selectedDate
        ? el.querySelector<HTMLElement>(
            `[data-cell-date="${CSS.escape(selectedDate)}"]`,
          )
        : null) ?? el.querySelector<HTMLElement>('[data-cell-state="today"]');
    if (!target) return;
    const offset =
      target.offsetLeft - el.clientWidth / 2 + target.clientWidth / 2;
    el.scrollLeft = Math.max(0, offset);
  });
</script>

<section
  class="grid-section"
  class:variant-dashboard={variant === "dashboard"}
  class:variant-daily-detail={variant === "daily-detail"}
>
  <div class="grid-toolbar">
    <span class="streak-info">
      {#if displayedWeek.my_streak && displayedWeek.my_streak.current > 0}
        <span>{displayedWeek.my_streak.current}-day streak</span>
        {#if displayedWeek.my_streak.freeze_count > 0}
          <span class="sep" aria-hidden="true">·</span>
          <span aria-hidden="true">❄</span>
          <span>
            {displayedWeek.my_streak.freeze_count}
            freeze{displayedWeek.my_streak.freeze_count !== 1 ? "s" : ""}
          </span>
        {/if}
      {/if}
    </span>
    <div class="grid-right">
      {#if displayedWeek.winners && displayedWeek.winners.length > 0}
        <span class="grid-winners">
          <span class="place">1st</span>
          {#if displayedWeek.winners.length === 1}
            <UserLink user={displayedWeek.winners[0].user} showBadge />
          {:else if displayedWeek.winners.length === 2}
            <UserLink user={displayedWeek.winners[0].user} showBadge />
            <span class="and"> &amp; </span>
            <UserLink user={displayedWeek.winners[1].user} showBadge />
          {:else}
            <UserLink user={displayedWeek.winners[0].user} showBadge />
            <span class="extra">+{displayedWeek.winners.length - 1}</span>
          {/if}
        </span>
      {/if}
      <div class="week-nav">
        <button
          type="button"
          class="nav-btn"
          data-week-nav="prev"
          aria-label="Previous week"
          onclick={() => navigate(-1)}
          disabled={navigating || !displayedWeek.has_earlier}
        >
          <span aria-hidden="true">&larr;</span>
        </button>
        <button
          type="button"
          class="nav-btn"
          data-week-nav="next"
          aria-label="Next week"
          onclick={() => navigate(1)}
          disabled={navigating || !canGoNext}
        >
          <span aria-hidden="true">&rarr;</span>
        </button>
      </div>
    </div>
  </div>
  <div class="grid-plate">
    <div class="grid" bind:this={scrollContainer}>
      {#each displayedWeek.days as day, dayIndex (day.date)}
        {@const href = hrefFor(day)}
        <svelte:element
          this={href ? "a" : "div"}
          href={href ?? undefined}
          class="cell"
          class:past={day.state === "past"}
          class:today={day.state === "today"}
          class:future={day.state === "future"}
          class:missing-past={day.state === "missing_past"}
          class:selected={day.date === selectedDate}
          data-cell-state={day.state}
          data-cell-date={day.date}
        >
          <div
            class="wl {wlClass(day)}"
            class:wl-first={dayIndex === 0}
            class:wl-last={dayIndex === displayedWeek.days.length - 1}
            aria-hidden="true"
          >
            {#if dayIndex === 0}
              <span class="wl-start"></span>
            {/if}
            <span class="wl-line"></span>
            <span class="wl-station"></span>
            {#if day.state === "today" && !myDone(day)}
              <span class="wl-train"></span>
            {/if}
            {#if dayIndex === displayedWeek.days.length - 1}
              <span class="wl-term" class:filled={weekOver}></span>
            {/if}
          </div>
          <div class="header">
            <span class="weekday">{WEEKDAY_LABELS[day.weekday]}</span>
            {#if day.state === "today"}
              <span class="today-label">Today</span>
            {:else if day.state === "past" && day.starters_count > 0}
              <span class="meta">
                {day.starters_count}
                {day.starters_count === 1 ? "player" : "players"}
              </span>
            {/if}
          </div>

          {#if day.state === "missing_past"}
            <span class="muted">No daily</span>
          {:else if day.state === "future"}
            <span class="pool">
              {day.pool_display_name ?? "TBD"}
              {#if day.deathless}
                <span class="deathless" title="Dying once eliminates you"
                  >Deathless</span
                >
              {/if}
            </span>
            <span class="countdown">Opens in {countdown(day.started_at)}</span>
          {:else}
            <span class="pool">
              {day.pool_display_name ?? "TBD"}
              {#if day.deathless}
                <span class="deathless" title="Dying once eliminates you"
                  >Deathless</span
                >
              {/if}
            </span>
            <div class="body">
              {#if day.state === "today"}
                {#if day.race_id === null}
                  <span class="muted">Daily seed incoming</span>
                {:else if day.participants_count > 0}
                  <span class="muted">
                    {day.participants_count}
                    {day.participants_count === 1 ? "player" : "players"}
                  </span>
                {/if}
              {:else}
                {@const winner =
                  day.podium.find((e) => e.placement === 1) ?? null}
                {#if winner}
                  <div class="winner">
                    <span class="place">1st</span>
                    <span class="name"
                      >{winner.twitch_display_name ??
                        winner.twitch_username}</span
                    >
                    <span class="igt">{formatIgt(winner.igt_ms)}</span>
                  </div>
                {:else}
                  <span class="muted">No finishers</span>
                {/if}
              {/if}
            </div>
            {@const strip = cellStrip(
              day,
              selectedDate,
              displayedWeek.my_streak?.current ?? 0,
            )}
            {#if strip?.kind === "label"}
              <span class="strip strip-{strip.variant}">{strip.text}</span>
            {:else if strip?.kind === "finished"}
              <span class="strip strip-finished">
                <span class="strip-icon" aria-hidden="true">✓</span>
                <span class="strip-score">{strip.score}</span>
              </span>
            {:else if strip?.kind === "dnf"}
              <span class="strip strip-dnf"
                >{strip.igt ? `DNF · ${strip.igt}` : "DNF"}</span
              >
            {:else}
              <span class="strip strip-placeholder" aria-hidden="true"
                >&nbsp;</span
              >
            {/if}
          {/if}
        </svelte:element>
      {/each}
    </div>
  </div>
</section>

<style>
  .grid-section {
    margin-bottom: 2rem;
  }

  .grid-section.variant-daily-detail {
    margin-bottom: 0;
  }

  /* One continuous timetable: hairline column separators inside a single
   * bordered plate, horizontal scroll below 7 * 150px. The plate carries
   * the border; the scroller inside extends its scrollport 8px upward
   * (padding-top + negative margin), which is what lets the week line
   * ride the plate's top border without being clipped by overflow-x. */
  .grid-plate {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(7, minmax(150px, 1fr));
    padding-top: 8px;
    margin-top: -8px;
    overflow-x: auto;
  }

  .cell {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0 0.875rem 0.75rem;
    min-height: 150px;
    min-width: 0;
    border-left: 1px solid var(--color-border);
    text-decoration: none;
    color: inherit;
    transition: background var(--transition);
  }

  .cell:first-child {
    border-left: none;
  }

  a.cell:hover,
  .cell.today,
  .cell.selected {
    background: var(--color-surface-elevated);
    --wl-hole: var(--color-surface-elevated);
  }

  /* Week line: one continuous route across the plate's top edge. Each cell
   * carries its own full-width segment (the 1px column separators read as
   * tick marks on the line) with a centered station; the first cell adds
   * the brass start triangle, the last one the brass terminal square. */
  .wl {
    flex: none;
    position: relative;
    height: 14px;
    /* Pull the segment up into the scroller's extra top padding so the
     * line lands on the plate's border and the stations straddle it. */
    margin: -8px -0.875rem 0.1rem;
  }

  .wl-line {
    position: absolute;
    left: 0;
    right: 0;
    top: 6px;
    border-top: 2px solid;
  }

  .wl-first .wl-line {
    left: 14px;
  }

  .wl-last .wl-line {
    right: 14px;
  }

  .wl-done .wl-line {
    border-top-color: var(--color-success);
  }

  .wl-closed .wl-line {
    border-top-color: var(--color-info);
  }

  .wl-today .wl-line {
    border-top-color: var(--color-danger);
  }

  .wl-playing .wl-line {
    border-top-color: var(--color-warning);
  }

  .wl-future .wl-line {
    border-top-style: dashed;
    border-top-color: var(--color-border);
  }

  .wl-station {
    position: absolute;
    left: 50%;
    top: 2px;
    width: 10px;
    height: 10px;
    margin-left: -5px;
    border-radius: 50%;
    border: 2px solid;
    background: var(--wl-hole, var(--color-surface));
  }

  .wl-done .wl-station {
    border-color: var(--color-success);
  }

  .wl-closed .wl-station {
    border-color: var(--color-info);
  }

  .wl-today .wl-station {
    border-color: var(--color-danger);
  }

  .wl-playing .wl-station {
    border-color: var(--color-warning);
  }

  .wl-future .wl-station {
    border-color: var(--color-text-disabled);
  }

  .wl-start {
    position: absolute;
    left: 2px;
    top: 1px;
    width: 0;
    height: 0;
    border-left: 10px solid var(--color-gold);
    border-top: 6px solid transparent;
    border-bottom: 6px solid transparent;
  }

  .wl-term {
    position: absolute;
    right: 2px;
    top: 3px;
    width: 8px;
    height: 8px;
    border: 2px solid var(--color-gold);
    background: var(--wl-hole, var(--color-surface));
  }

  .wl-term.filled {
    border: none;
    background: var(--color-gold);
  }

  .wl-train {
    position: absolute;
    left: 0;
    right: 0;
    top: 4px;
    height: 6px;
    pointer-events: none;
    overflow: hidden;
  }

  /* Keep the dot on the line where the first/last cells inset it for the
   * brass start and terminal markers. */
  .wl-first .wl-train {
    left: 14px;
  }

  .wl-last .wl-train {
    right: 14px;
  }

  .wl-train::before {
    content: "";
    position: absolute;
    inset: 0;
    background: radial-gradient(
      circle 3px at 3px 3px,
      var(--color-danger) 98%,
      transparent
    );
    background-repeat: no-repeat;
    animation: route-ride 3.2s linear infinite;
  }

  .wl-playing .wl-train::before {
    background: radial-gradient(
      circle 3px at 3px 3px,
      var(--color-warning) 98%,
      transparent
    );
    background-repeat: no-repeat;
  }

  @media (prefers-reduced-motion: reduce) {
    .wl-train {
      display: none;
    }
  }

  .cell.future,
  .cell.missing-past {
    opacity: 0.55;
    cursor: not-allowed;
  }

  .cell.selected {
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.45);
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }

  .weekday,
  .meta {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  .today-label {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-gold);
  }

  .pool {
    min-width: 0;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 1.05rem;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--color-text);
  }

  .cell.future .pool {
    color: var(--color-text-secondary);
  }

  .pool .deathless {
    display: inline-block;
    margin-left: 0.3rem;
    font-family: var(--font-mono);
    font-size: 0.6rem;
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-danger);
    cursor: default;
  }

  .body {
    flex: 1;
    display: flex;
    flex-direction: column;
    justify-content: center;
    min-height: 0;
  }

  .winner {
    display: flex;
    gap: 0.35rem;
    align-items: baseline;
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
  }

  .winner .place {
    flex: none;
    font-size: 0.7rem;
    color: var(--color-gold);
  }

  .winner .name {
    color: var(--color-text);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .winner .igt {
    margin-left: auto;
    color: var(--color-text-secondary);
  }

  /* Strips: the cell's bottom edge carries my state (hue taxonomy from
   * cellStrip; solid verdigris = the action, everything else quiet). */
  .strip {
    margin: auto -0.875rem -0.75rem;
    padding: 0.34rem 0.5rem 0.42rem;
    text-align: center;
    font-family: var(--font-display);
    font-weight: 600;
    font-size: 0.85rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }

  .strip-play-now {
    background: var(--color-success);
    color: #0d1a15;
  }

  a.cell:hover .strip-play-now {
    background: #5fc2a0;
  }

  .strip-in-progress {
    background: rgba(200, 164, 78, 0.16);
    color: var(--color-gold);
  }

  .strip-freeze {
    background: rgba(159, 214, 232, 0.14);
    color: var(--color-frost);
  }

  .strip-abandoned {
    background: rgba(135, 145, 160, 0.14);
    color: var(--color-text-disabled);
  }

  .strip-finished,
  .strip-dnf {
    background: rgba(135, 145, 160, 0.14);
    font-family: var(--font-mono);
    font-weight: 500;
    font-size: 0.75rem;
    letter-spacing: 0.04em;
  }

  .strip-finished {
    display: flex;
    align-items: baseline;
    justify-content: center;
    gap: 0.4rem;
    color: var(--color-success);
  }

  .strip-finished .strip-icon {
    font-weight: 600;
  }

  .strip-dnf {
    color: var(--color-text-secondary);
  }

  .strip-placeholder {
    visibility: hidden;
  }

  .countdown {
    margin-top: auto;
    padding-bottom: 0.2rem;
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    text-align: center;
  }

  .muted {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  @media (max-width: 640px) {
    .grid {
      scroll-snap-type: x mandatory;
    }
    .cell {
      scroll-snap-align: center;
    }
  }

  .grid-toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    /* The week line's stations straddle the plate's top border below;
     * keep enough air for their upper halves. */
    gap: 1rem;
    margin-bottom: 0.6rem;
  }

  .streak-info {
    display: inline-flex;
    gap: 0.25rem;
    align-items: baseline;
    font-family: var(--font-mono);
    font-size: 0.75rem;
    letter-spacing: 0.05em;
    color: var(--color-text-secondary);
  }

  .streak-info .sep {
    margin: 0 0.25rem;
    color: var(--color-text-disabled);
  }

  .grid-right {
    display: inline-flex;
    align-items: center;
    gap: 0.7rem;
  }

  .grid-winners {
    display: inline-flex;
    align-items: center;
    gap: 0.35rem;
    color: var(--color-text);
    font-size: var(--font-size-sm);
    font-weight: 500;
  }

  .grid-winners .place {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    color: var(--color-gold);
  }

  .grid-winners .and,
  .grid-winners .extra {
    color: var(--color-text-secondary);
  }

  .week-nav {
    display: flex;
    gap: 0.25rem;
  }

  .nav-btn {
    appearance: none;
    background: transparent;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    color: var(--color-text-secondary);
    width: 1.75rem;
    height: 1.75rem;
    cursor: pointer;
    display: inline-flex;
    align-items: center;
    justify-content: center;
    font-family: inherit;
    font-size: 0.95rem;
    line-height: 1;
    transition:
      color var(--transition),
      border-color var(--transition);
  }

  .nav-btn:hover:not(:disabled) {
    color: var(--color-purple);
    border-color: var(--color-purple);
  }

  .nav-btn:disabled {
    opacity: 0.4;
    cursor: not-allowed;
  }
</style>
