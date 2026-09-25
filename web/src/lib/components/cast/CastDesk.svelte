<script lang="ts">
  import { page } from "$app/state";
  import { raceStore } from "$lib/stores/race.svelte";
  import { sceneLayout, type CastSceneId } from "$lib/cast/layout";
  import { parseCastParams } from "$lib/cast/params";
  import { formatElapsed, formatCountdown } from "$lib/cast/clock";
  import type { RaceDetail } from "$lib/api";

  interface Props {
    scene: CastSceneId;
    race: RaceDetail;
    cams: number;
    casters: [string | null, string | null];
  }

  let { scene, race, cams, casters }: Props = $props();

  let layout = $derived(sceneLayout(scene, { cams }));
  let panels = $derived(layout.panels);
  let camHoles = $derived(layout.holes.filter((h) => h.role === "cam"));

  // raceStore carries the live values once connected; the initial REST fetch
  // (`race`) is what the page paints before the WebSocket catches up, same
  // fallback the existing overlays use.
  let status = $derived(raceStore.race?.status ?? race.status);
  let startedAt = $derived(raceStore.race?.started_at ?? race.started_at);
  let raceEndsAt = $derived(raceStore.race?.race_ends_at ?? race.race_ends_at);

  // The clock lags by the same delay the rest of the scene's data does
  // (raceStore.connect's delay queue), read straight from the URL like the
  // rest of a cast scene's own parameters, so the elapsed time on screen
  // always matches what the caster's delayed video is showing.
  let delayMs = $derived(parseCastParams(page.url).delayMs);

  let now = $state(Date.now());
  $effect(() => {
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

  // Best-effort stage label from the race's own event slot. A stage race's
  // slot is "<stage_key>:<index>" (server/services/event_service.py's
  // parse_slot), e.g. "semi_b:1"; humanising the key gives "Semi B", which
  // matches this event's real stage labels (server/tests/test_event_config.py
  // pairs "semi_b" with "Semi B", "newcomers" with "Newcomers", and so on).
  // RaceDetail carries only the event's id (a UUID), not its stage list
  // where the canonical label actually lives, so this is a local guess, not
  // a fetch of the real thing. A qualifier slot ("qualifier:<mode>:<n>") has
  // no stage to name, so it is left out rather than humanised into nonsense.
  function formatStage(slot: string | null): string | null {
    if (!slot) return null;
    const parts = slot.split(":");
    if (parts.length !== 2) return null;
    return parts[0]
      .split(/[_-]/)
      .filter(Boolean)
      .map((w) => w[0].toUpperCase() + w.slice(1))
      .join(" ");
  }
  let stageLabel = $derived(formatStage(race.event_slot));
  let modeLabel = $derived(race.pool_display_name ?? race.pool_name ?? "");

  // The partner co-brand. RaceDetail only carries the event's id, and no
  // client endpoint resolves an id to an EventDetail (fetchEvent takes a
  // slug), so the partner name is not reachable here today. Every race
  // therefore takes the documented no-partner degrade below: the lockup
  // shows the SpeedFog wordmark alone rather than a hole where the partner
  // would sit.
  let partnerName: string | null = null;
</script>

{#if panels.race}
  <div
    class="race-zone"
    style="left: {panels.race.x}px; top: {panels.race.y}px; width: {panels.race
      .w}px; height: {panels.race.h}px;"
  >
    {#if stageLabel}<span class="rz1">{stageLabel}</span>{/if}
    <span class="rz2">{race.name}</span>
    {#if modeLabel}<span class="rz3">{modeLabel}</span>{/if}
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
    <span class="cz-big">{formatElapsed(elapsedMs)}</span>
    {#if endsInText}
      <span class="cz-end">Ends in <b>{endsInText}</b></span>
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

  .pill-live {
    color: var(--color-danger);
    border-color: var(--color-danger);
    background: color-mix(in srgb, var(--color-danger) 12%, transparent);
  }

  .pill-finished {
    color: var(--color-info);
    border-color: var(--color-info);
    background: color-mix(in srgb, var(--color-info) 12%, transparent);
  }

  .pill-upcoming {
    color: var(--color-text-secondary);
    border-color: var(--color-text-secondary);
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
    background: color-mix(in srgb, var(--color-bg) 86%, transparent);
    font-family: var(--font-mono);
    font-size: 15px;
    letter-spacing: 0.1em;
    text-transform: uppercase;
    color: var(--color-text);
  }
</style>
