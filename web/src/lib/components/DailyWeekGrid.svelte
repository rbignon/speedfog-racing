<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type { DailyWeekDay, DailyWeekResponse } from "$lib/api";
  import { fetchDailyWeek } from "$lib/api";
  import { formatIgt } from "$lib/utils/training";

  interface Props {
    week: DailyWeekResponse;
    variant?: "home" | "dashboard" | "daily-detail";
    selectedDate?: string;
  }

  let { week, variant = "home", selectedDate }: Props = $props();

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

  type CellStrip =
    | {
        kind: "label";
        text: string;
        variant: "play-now" | "in-progress" | "abandoned";
      }
    | {
        kind: "finished";
        score: string;
      }
    | null;

  function finishedScore(day: DailyWeekDay): string {
    const r = day.my_result;
    if (r && r.status === "finished" && r.placement && r.igt_ms != null) {
      return `${r.placement}/${r.total_starters} · ${formatIgt(r.igt_ms)}`;
    }
    return "Done";
  }

  function cellStrip(day: DailyWeekDay): CellStrip {
    if (day.state === "today") {
      const r = day.my_result;
      if (!r) {
        // The today cell can also be the selected cell when the viewer is
        // on /daily/[today]. The "Play now" CTA is redundant in that case
        // since clicking it would take them to the page they're already on.
        if (day.date === selectedDate) return null;
        return { kind: "label", text: "Play now", variant: "play-now" };
      }
      if (r.status === "finished")
        return { kind: "finished", score: finishedScore(day) };
      if (r.status === "abandoned")
        return { kind: "label", text: "Abandoned", variant: "abandoned" };
      // registered, ready, playing
      return { kind: "label", text: "In progress", variant: "in-progress" };
    }
    if (day.state === "past") {
      const r = day.my_result;
      if (!r) return null;
      if (r.status === "finished")
        return { kind: "finished", score: finishedScore(day) };
      if (r.status === "playing")
        return { kind: "label", text: "In progress", variant: "in-progress" };
      // abandoned, registered, ready (signed up but never played)
      return { kind: "label", text: "Abandoned", variant: "abandoned" };
    }
    return null;
  }

  function hrefFor(day: DailyWeekDay): string | null {
    if (day.state === "today") return "/daily";
    if (day.state === "past") return `/daily/${day.date}`;
    return null;
  }

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
  <div class="grid" bind:this={scrollContainer}>
    {#each displayedWeek.days as day (day.date)}
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
        <div class="header">
          <span class="weekday">{WEEKDAY_LABELS[day.weekday]}</span>
          {#if day.state === "today"}
            <span class="badge today">Today</span>
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
          <span class="pool">{day.pool_display_name ?? "TBD"}</span>
          <span class="countdown">Opens in {countdown(day.started_at)}</span>
        {:else}
          <span class="pool">{day.pool_display_name ?? "TBD"}</span>
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
                  <span class="medal" aria-hidden="true">🥇</span>
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
          {@const strip = cellStrip(day)}
          {#if strip?.kind === "label"}
            <span class="strip strip-{strip.variant}">{strip.text}</span>
          {:else if strip?.kind === "finished"}
            <span class="strip strip-finished">
              <span class="strip-icon" aria-hidden="true">✓</span>
              <span class="strip-score">{strip.score}</span>
            </span>
          {:else}
            <span class="strip strip-placeholder" aria-hidden="true"
              >&nbsp;</span
            >
          {/if}
        {/if}
      </svelte:element>
    {/each}
  </div>
</section>

<style>
  .grid-section {
    position: relative;
    margin-bottom: 2rem;
  }

  .grid-section.variant-daily-detail {
    margin-bottom: 0;
  }

  .grid {
    display: grid;
    grid-template-columns: repeat(7, minmax(150px, 1fr));
    gap: 0.5rem;
    overflow-x: auto;
    /* overflow-x: auto computes overflow-y to auto too, which would
       clip the today cell's outer gold glow at the top/bottom edges.
       Pad so the glow has breathing room before clipping. */
    padding: 0.75rem 0.5rem;
  }

  .cell {
    display: flex;
    flex-direction: column;
    gap: 0.25rem;
    padding: 0.75rem 0.875rem;
    min-height: 150px;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    text-decoration: none;
    color: inherit;
    transition: border-color var(--transition);
  }
  a.cell:hover {
    border-color: var(--color-purple);
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  }

  .cell.today {
    box-shadow: 0 0 20px rgba(200, 164, 78, 0.18);
  }
  a.cell.today:hover {
    box-shadow:
      0 0 20px rgba(200, 164, 78, 0.18),
      0 2px 8px rgba(0, 0, 0, 0.2);
  }

  .cell.future,
  .cell.missing-past {
    border-style: dashed;
    opacity: 0.55;
    cursor: not-allowed;
  }

  .cell.selected {
    background: var(--color-surface-elevated);
    box-shadow: inset 0 2px 6px rgba(0, 0, 0, 0.45);
  }
  .cell.today.selected {
    box-shadow:
      inset 0 2px 6px rgba(0, 0, 0, 0.45),
      0 0 20px rgba(200, 164, 78, 0.18);
  }
  a.cell.selected:hover {
    border-color: var(--color-purple);
    box-shadow:
      inset 0 2px 6px rgba(0, 0, 0, 0.45),
      0 2px 8px rgba(0, 0, 0, 0.2);
  }
  a.cell.today.selected:hover {
    box-shadow:
      inset 0 2px 6px rgba(0, 0, 0, 0.45),
      0 0 20px rgba(200, 164, 78, 0.18),
      0 2px 8px rgba(0, 0, 0, 0.2);
  }

  .header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
  }
  .weekday {
    font-size: var(--font-size-xs);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    font-weight: 600;
    color: var(--color-text-secondary);
  }
  .meta {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }
  .badge.today {
    padding: 0;
    font-size: var(--font-size-xs);
    color: var(--color-gold);
    font-weight: 600;
  }

  .pool {
    font-weight: 600;
    color: var(--color-text);
    font-size: var(--font-size-sm);
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
    font-size: var(--font-size-xs);
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
    font-variant-numeric: tabular-nums;
  }
  .strip {
    margin-top: auto;
    padding: 0.4rem 0.5rem;
    text-align: center;
    font-weight: 700;
    font-size: var(--font-size-sm);
    text-transform: uppercase;
    letter-spacing: 0.1em;
    border-radius: 0 0 calc(var(--radius-md) - 1px) calc(var(--radius-md) - 1px);
    margin-left: -0.875rem;
    margin-right: -0.875rem;
    margin-bottom: -0.75rem;
  }
  .strip-play-now {
    background: rgba(16, 185, 129, 0.12);
    color: var(--color-success);
  }
  .strip-finished {
    background: rgba(107, 114, 128, 0.18);
    color: var(--color-success);
    display: flex;
    justify-content: space-between;
    align-items: center;
    padding-left: 0.875rem;
    padding-right: 0.875rem;
    letter-spacing: 0.04em;
    font-variant-numeric: tabular-nums;
  }
  .strip-in-progress {
    background: rgba(245, 158, 11, 0.14);
    color: #f59e0b;
  }
  .strip-abandoned {
    background: rgba(107, 114, 128, 0.18);
    color: var(--color-text-disabled);
  }
  .strip-placeholder {
    visibility: hidden;
  }
  .countdown {
    margin-top: auto;
    color: var(--color-text);
    font-variant-numeric: tabular-nums;
    font-size: var(--font-size-sm);
    text-align: center;
  }
  .muted {
    color: var(--color-text-disabled);
    font-style: italic;
    font-size: var(--font-size-xs);
  }

  @media (max-width: 640px) {
    .grid {
      scroll-snap-type: x mandatory;
    }
    .cell {
      scroll-snap-align: center;
    }
  }

  .week-nav {
    position: absolute;
    right: 0;
    bottom: calc(100% + 0.25rem);
    display: flex;
    gap: 0.25rem;
    z-index: 1;
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
