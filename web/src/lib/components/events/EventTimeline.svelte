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
  let doneWidth = $derived(currentIndex < 0 ? 0 : placed[currentIndex].x);
</script>

<div class="tl" aria-hidden="true">
  <span class="rail"></span>
  <span class="rail-done" style="width: calc({doneWidth}% - 6px)"></span>
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
  .rail {
    position: absolute;
    left: 6px;
    right: 6px;
    top: 12px;
    height: 2px;
    background: var(--color-border);
  }
  .rail-done {
    position: absolute;
    left: 6px;
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
  .g.announce {
    width: 0;
    height: 0;
    top: 6px;
    background: none;
    border-left: 6px solid transparent;
    border-right: 6px solid transparent;
    border-bottom: 12px solid var(--color-gold);
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
  .g.semi.done {
    background: var(--color-purple);
  }
  .g.semi.now {
    background: var(--color-danger);
  }
  .g.newcomers.done,
  .g.final.done {
    background: var(--color-info);
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
