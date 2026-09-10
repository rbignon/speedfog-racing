<script lang="ts">
  import type { EventTimelineStop } from "$lib/api";

  let { stops, now }: { stops: EventTimelineStop[]; now: Date } = $props();

  const day = new Intl.DateTimeFormat("en-GB", {
    day: "numeric",
    month: "short",
  });
  let placed = $derived(
    stops.map((s, i) => ({
      ...s,
      x: stops.length === 1 ? 50 : 3 + (i * 93) / (stops.length - 1),
      done: new Date(s.date).getTime() <= now.getTime(),
    })),
  );
  let currentIndex = $derived(
    placed.reduce((acc, s, i) => (s.done ? i : acc), -1),
  );
  // The ridden stretch runs from the first stop to the current one, then on
  // towards the next stop in proportion to the time elapsed, so a week
  // between two Sundays reads as a half-ridden segment on the Wednesday.
  // Before the first stop the width computes to a negative length, which the
  // browser clamps to zero.
  let doneX = $derived.by(() => {
    if (currentIndex < 0) return placed[0]?.x ?? 0;
    const cur = placed[currentIndex];
    const next = placed[currentIndex + 1];
    if (!next) return cur.x;
    const t0 = new Date(cur.date).getTime();
    const t1 = new Date(next.date).getTime();
    const elapsed = t1 > t0 ? (now.getTime() - t0) / (t1 - t0) : 0;
    return cur.x + (next.x - cur.x) * Math.min(1, Math.max(0, elapsed));
  });
  let firstX = $derived(placed[0]?.x ?? 0);
  let lastX = $derived(placed.at(-1)?.x ?? 0);
</script>

<div class="tl" aria-hidden="true">
  <span
    class="rail"
    style="left: calc({firstX}% + 6px); right: calc({100 - lastX}% + 6px)"
  ></span>
  <span
    class="rail-done"
    style="left: calc({firstX}% + 6px); width: calc({doneX - firstX}% - 6px)"
  ></span>
  {#each placed as stop, i (stop.key)}
    <div class="stop" style="left: {stop.x}%">
      <span
        class="g {stop.kind}"
        class:done={stop.done}
        class:now={i === currentIndex}
      ></span>
      <div class="lbl">
        <div class="t" class:dim={!stop.done}>{stop.label}</div>
        <div class="s">{day.format(new Date(stop.date))}</div>
      </div>
    </div>
  {/each}
</div>

<style>
  .tl {
    position: relative;
    width: min(640px, 100%);
    height: 78px;
    margin: 0.9rem 0 0;
  }
  /* The rail starts after the departure triangle and stops at the terminal
   * square; both ends are set inline from the stops' positions. */
  .rail {
    position: absolute;
    top: 12px;
    height: 2px;
    background: var(--color-border);
  }
  .rail-done {
    position: absolute;
    top: 12px;
    height: 2px;
    background: var(--color-gold);
  }
  .stop {
    position: absolute;
    top: 0;
    width: 0;
  }
  .g {
    position: absolute;
    left: -6px;
    top: 7px;
    width: 12px;
    height: 12px;
    background: var(--color-border);
  }
  /* Departure: a triangle pointing down the line */
  .g.announce {
    width: 0;
    height: 0;
    background: none;
    border-top: 6px solid transparent;
    border-bottom: 6px solid transparent;
    border-left: 12px solid var(--color-border);
  }
  .g.announce.done {
    border-left-color: var(--color-gold);
  }
  .g.announce.now {
    filter: drop-shadow(0 0 6px rgba(200, 164, 78, 0.35));
  }
  .g.open,
  .g.cut {
    border-radius: 50%;
    border: 2px solid var(--color-border);
    background: var(--color-surface);
    box-sizing: border-box;
  }
  .g.open.done,
  .g.cut.done {
    border-color: var(--color-gold);
  }
  .g.open.now,
  .g.cut.now {
    background: var(--color-gold);
    box-shadow: var(--glow-gold);
  }
  .g.semi {
    transform: rotate(45deg) scale(0.8);
  }
  /* Passed stops ride in brass whatever their shape; the current one glows */
  .g.semi.done,
  .g.newcomers.done,
  .g.final.done {
    background: var(--color-gold);
  }
  .g.semi.now,
  .g.newcomers.now,
  .g.final.now {
    box-shadow: var(--glow-gold);
  }
  .lbl {
    position: absolute;
    top: 28px;
    left: -48px;
    width: 96px;
    text-align: center;
  }
  .t {
    font-family: var(--font-display);
    text-transform: uppercase;
    font-weight: 600;
    font-size: 0.9rem;
    letter-spacing: 0.03em;
    line-height: 1.1;
  }
  .t.dim {
    color: var(--color-text-secondary);
  }
  .s {
    font-family: var(--font-mono);
    font-size: 0.66rem;
    color: var(--color-text-secondary);
    margin-top: 2px;
  }
</style>
