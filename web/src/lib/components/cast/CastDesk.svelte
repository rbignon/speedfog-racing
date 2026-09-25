<script lang="ts">
  import { page } from "$app/state";
  import { raceStore } from "$lib/stores/race.svelte";
  import { sceneLayout, type CastSceneId } from "$lib/cast/layout";
  import { parseCastParams } from "$lib/cast/params";
  import { formatElapsed, formatCountdown } from "$lib/cast/clock";
  import { splitRaceName } from "$lib/cast/race-name";
  import type { RaceDetail } from "$lib/api";

  interface Props {
    scene: CastSceneId;
    /** Absent on the talk scene: it has no single race to describe, and its
     * layout carries no `race` or `clock` panel for this component to draw
     * into, so the race-zone and clock-zone blocks below simply don't
     * render. Every other scene always passes one. */
    race?: RaceDetail;
    cams: number;
    casters: [string | null, string | null];
    /** The co-brand's name, resolved by the route from `?event=<slug>`; null
     * off an event, or when that slug fails to resolve. */
    partnerName: string | null;
  }

  let { scene, race, cams, casters, partnerName }: Props = $props();

  let layout = $derived(sceneLayout(scene, { cams }));
  let panels = $derived(layout.panels);
  let camHoles = $derived(layout.holes.filter((h) => h.role === "cam"));

  // raceStore carries the live values once connected; the initial REST fetch
  // (`race`) is what the page paints before the WebSocket catches up, same
  // fallback the existing overlays use. Neither exists on the talk scene
  // (no race, no socket), so these fall back to a harmless default that is
  // never actually shown, since `panels.clock` is absent there too.
  let status = $derived(raceStore.race?.status ?? race?.status ?? "setup");
  let startedAt = $derived(
    raceStore.race?.started_at ?? race?.started_at ?? null,
  );
  let raceEndsAt = $derived(
    raceStore.race?.race_ends_at ?? race?.race_ends_at ?? null,
  );

  // The clock lags by the same delay the rest of the scene's data does
  // (raceStore.connect's delay queue), read straight from the URL like the
  // rest of a cast scene's own parameters, so the elapsed time on screen
  // always matches what the caster's delayed video is showing.
  let delayMs = $derived(parseCastParams(page.url).delayMs);

  // A finished race has no clock to keep. Freezing at race_ends_at was
  // considered and rejected: a race everyone finished early would then show
  // a time longer than it actually ran. Showing nothing claims nothing, so
  // the interval stops rather than ticking on for a clock nobody reads.
  let now = $state(Date.now());
  $effect(() => {
    if (!panels.clock || status === "finished") return;
    const id = setInterval(() => {
      now = Date.now();
    }, 1000);
    return () => clearInterval(id);
  });
  let shiftedNow = $derived(now - delayMs);

  let elapsedMs = $derived(
    startedAt ? shiftedNow - new Date(startedAt).getTime() : 0,
  );
  let countdownMs = $derived(
    raceEndsAt ? new Date(raceEndsAt).getTime() - shiftedNow : null,
  );
  // "Ends in" only means something while the race is actually running.
  let endsInText = $derived(
    status === "running" ? formatCountdown(countdownMs) : null,
  );

  let pillText = $derived(
    status === "running"
      ? "Live"
      : status === "finished"
        ? "Finished"
        : "Upcoming",
  );
  let pillClass = $derived(
    status === "running"
      ? "live"
      : status === "finished"
        ? "finished"
        : "upcoming",
  );

  // The race-zone lines come from the organizer-authored name, not from
  // event_slot (a routing key, not a display string; see race-name.ts). A
  // name that doesn't split still needs to look intentional, not like a
  // stray secondary line, so a single line takes the prominent style (rz2)
  // rather than the small one (rz1) a first part would otherwise get.
  const RACE_LINE_CLASSES: Record<number, readonly string[]> = {
    1: ["rz2"],
    2: ["rz1", "rz2"],
    3: ["rz1", "rz2", "rz3"],
  };
  let raceLines = $derived(
    race
      ? splitRaceName(race.name).map((text, i, all) => ({
          text,
          cls: RACE_LINE_CLASSES[all.length][i],
        }))
      : [],
  );
</script>

{#if panels.race}
  <div
    class="race-zone"
    style="left: {panels.race.x}px; top: {panels.race.y}px; width: {panels.race
      .w}px; height: {panels.race.h}px;"
  >
    {#each raceLines as line, i (i)}
      <span class={line.cls}>{line.text}</span>
    {/each}
  </div>
{/if}

{#if panels.lockup}
  <div
    class="lock"
    style="left: {panels.lockup.x}px; top: {panels.lockup.y}px; width: {panels
      .lockup.w}px; height: {panels.lockup.h}px;"
  >
    <span class="lk1">Speedfog <em>Racing</em></span>
    {#if partnerName}
      <span class="lk2">&times;</span>
      <span class="lk3">{partnerName}</span>
    {/if}
  </div>
{/if}

{#if panels.clock}
  <div
    class="clock-zone"
    style="left: {panels.clock.x}px; top: {panels.clock.y}px; width: {panels
      .clock.w}px; height: {panels.clock.h}px;"
  >
    <span class="pill pill-{pillClass}">{pillText}</span>
    {#if status !== "finished"}
      <span class="cz-big">{formatElapsed(elapsedMs)}</span>
      {#if endsInText}
        <span class="cz-end">Ends in <b>{endsInText}</b></span>
      {/if}
    {/if}
  </div>
{/if}

{#each camHoles as hole, i (hole.id)}
  <div
    class="cam-frame"
    style="left: {hole.x}px; top: {hole.y}px; width: {hole.w}px; height: {hole.h}px;"
  >
    {#if casters[i]}
      <span class="camname">{casters[i]}</span>
    {/if}
  </div>
{/each}

<style>
  .race-zone {
    position: absolute;
    display: flex;
    flex-direction: column;
    justify-content: center;
    gap: 2px;
    font-family: var(--font-display);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
    line-height: 1.05;
  }

  .rz1 {
    font-size: 30px;
    color: var(--color-text-secondary);
  }

  .rz2 {
    font-size: 44px;
  }

  .rz3 {
    font-size: 30px;
    color: var(--color-gold);
  }

  .lock {
    position: absolute;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 2px;
    text-align: center;
    font-family: var(--font-display);
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.04em;
  }

  .lk1 {
    font-size: 38px;
    line-height: 1;
  }

  .lk1 em {
    font-style: normal;
    color: var(--color-gold);
  }

  .lk2 {
    font-size: 26px;
    color: var(--color-text-secondary);
    line-height: 1.1;
  }

  .lk3 {
    font-size: 38px;
    line-height: 1;
  }

  .clock-zone {
    position: absolute;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    justify-content: center;
    gap: 6px;
  }

  .pill {
    font-family: var(--font-mono);
    font-size: 15px;
    font-weight: 600;
    letter-spacing: 0.09em;
    padding: 3px 10px;
    text-transform: uppercase;
    border: 1px solid transparent;
  }

  /* Every color-mix() below has a literal fallback declared first: OBS
   * builds in the field still ship Chromium 103, which predates
   * color-mix() (needs 111). The literal is kept when unsupported and
   * overridden by the color-mix() line when it is. */
  .pill-live {
    color: var(--color-danger);
    border-color: var(--color-danger);
    background: rgba(220, 106, 81, 0.12);
    background: color-mix(in srgb, var(--color-danger) 12%, transparent);
  }

  .pill-finished {
    color: var(--color-info);
    border-color: var(--color-info);
    background: rgba(123, 162, 204, 0.12);
    background: color-mix(in srgb, var(--color-info) 12%, transparent);
  }

  .pill-upcoming {
    color: var(--color-text-secondary);
    border-color: var(--color-text-secondary);
    background: rgba(150, 160, 173, 0.12);
    background: color-mix(
      in srgb,
      var(--color-text-secondary) 12%,
      transparent
    );
  }

  .cz-big {
    font-family: var(--font-mono);
    font-size: 58px;
    font-weight: 600;
    line-height: 1;
    letter-spacing: 0.01em;
  }

  .cz-end {
    font-family: var(--font-mono);
    font-size: 18px;
    color: var(--color-text-secondary);
  }

  .cz-end b {
    color: var(--color-gold);
    font-weight: 600;
  }

  .cam-frame {
    position: absolute;
    pointer-events: none;
  }

  .camname {
    position: absolute;
    left: 0;
    bottom: 0;
    padding: 5px 14px;
    /* Load-bearing scrim (the caster name sits over the video hole), so the
     * literal fallback comes first; see the note above .pill-live. */
    background: rgba(15, 25, 35, 0.86);
    background: color-mix(in srgb, var(--color-bg) 86%, transparent);
    font-family: var(--font-mono);
    font-size: 15px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-text);
  }
</style>
