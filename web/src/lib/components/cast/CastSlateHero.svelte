<script lang="ts">
  import type { EventShowcase, EventStage, User } from "$lib/api";
  import type { Rect, SlateSceneId } from "$lib/cast/layout";
  import { endHeadline, introClock } from "$lib/cast/slates";
  import { rewards } from "$lib/stores/rewards.svelte";

  interface Props {
    scene: SlateSceneId;
    /** The band talk gives its cams and lockup. */
    rect: Rect;
    eventName: string;
    /** The event's co-brand, beside SpeedFog Racing; null when it has none. */
    partnerName: string | null;
    /** The freshest copy of the stage (see CastEvening). */
    stage: EventStage | EventShowcase;
    /** The stage each advancing place goes on to, by place. */
    nextLabels: (string | null)[];
  }

  let { scene, rect, eventName, partnerName, stage, nextLabels }: Props =
    $props();

  // The intro's countdown ticks as its own second turns over (it reads
  // rounded up, so 12:35 holds until 12:34 begins), and stops once the start
  // has passed: "Starting soon" has nothing left to count.
  let now = $state(Date.now());
  $effect(() => {
    if (scene !== "intro" || !stage.date || !stage.time_set) return;
    const target = Date.parse(stage.date);
    let timer: ReturnType<typeof setTimeout> | undefined;
    // Reads its own clock, never `now`: the effect stays keyed on the stage.
    const step = () => {
      const at = Date.now();
      now = at;
      const left = target - at;
      if (left > 0) timer = setTimeout(step, (left % 1000) + 5);
    };
    step();
    return () => clearTimeout(timer);
  });

  let clock = $derived(
    scene === "intro" ? introClock(stage.date, stage.time_set, now) : null,
  );
  let headline = $derived(
    scene === "end" ? endHeadline(stage, nextLabels) : null,
  );

  function displayName(u: User): string {
    return u.twitch_display_name || u.twitch_username;
  }

  function initial(u: User): string {
    return displayName(u).charAt(0).toUpperCase();
  }

  // Applied through a Svelte style binding, never concatenated into HTML: a
  // template's name_css can carry a double-quoted value. Mirrors
  // CastRoundStandings' own nameStyleFor, so a runner reads the same in the
  // hero and in the standings under it.
  function nameStyleFor(u: User): string {
    const id = u.equipped_name_template_id;
    const t = !id || id === "default" ? null : rewards.lookupTemplate(id);
    const parts: string[] = [];
    if (t?.gradient) {
      parts.push(
        `background: linear-gradient(90deg, ${t.gradient[0]}, ${t.gradient[1]});`,
        "-webkit-background-clip: text;",
        "background-clip: text;",
        "color: transparent;",
        "padding-inline-end: 0.1em;",
      );
    } else if (t?.color) {
      parts.push(`color: ${t.color};`);
    }
    if (t?.name_css) {
      parts.push(t.name_css);
    }
    return parts.join(" ");
  }
</script>

{#snippet lockup(cls: string)}
  <span class="lock {cls}"
    >Speedfog <em>Racing</em>{#if partnerName}<span class="x">&times;</span
      >{partnerName}{/if}</span
  >
{/snippet}

<div
  class="hero"
  style="left: {rect.x}px; top: {rect.y}px; width: {rect.w}px; height: {rect.h}px;"
>
  {#if scene === "intro"}
    {@render lockup("lock-lg")}
    <span class="ev">{eventName}</span>
    <span class="stage"
      >{stage.label}{#if stage.kind !== "showcase"}<span class="kind"
          >Playoff</span
        >{/if}</span
    >
    {#if clock}
      <span class="clock">
        {#if clock.label}<span class="clock-label">{clock.label}</span>{/if}
        <span class="clock-text" class:words={!clock.label}>{clock.text}</span>
      </span>
    {/if}
  {:else if scene === "pause"}
    <span class="brb">Be right back</span>
    <span class="rule"></span>
    <span class="where"
      >{eventName}<span class="dot">&middot;</span><span class="gold"
        >{stage.label}</span
      ></span
    >
    {@render lockup("lock-sm")}
  {:else if headline}
    <span class="eyebrow">{headline.provisional ? "Provisional" : " "}</span>
    <span class="headline"
      >{eventName}<span class="dot">&middot;</span><span class="gold"
        >{stage.label}</span
      ><span class="dot">&middot;</span>{headline.title}</span
    >
    <!-- Before any result the standings beneath already say so: the card
         keeps its line alone rather than repeat them. -->
    {#if headline.runners.length > 0}
      <div class="headliners">
        {#each headline.runners as { entry, next } (entry.user.id)}
          <div class="headliner">
            {#if entry.user.twitch_avatar_url}
              <img class="hav" src={entry.user.twitch_avatar_url} alt="" />
            {:else}
              <span class="hav hav-placeholder">{initial(entry.user)}</span>
            {/if}
            <span class="hn" style={nameStyleFor(entry.user)}
              >{displayName(entry.user)}</span
            >
            <span class="hl">
              <span class="hp">{entry.points}</span>
              {#if next}<span class="chip">{next}</span>{/if}
            </span>
          </div>
        {/each}
      </div>
    {/if}
  {/if}
</div>

<style>
  .hero {
    position: absolute;
    display: flex;
    flex-direction: column;
    align-items: center;
    justify-content: center;
    gap: 18px;
    text-align: center;
    font-family: var(--font-display);
    font-weight: 600;
    text-transform: uppercase;
  }

  .hero > * {
    max-width: 100%;
  }

  .lock {
    letter-spacing: 0.04em;
  }

  .lock em {
    font-style: normal;
    color: var(--color-gold);
  }

  .lock .x {
    margin: 0 10px;
    color: var(--color-text-secondary);
  }

  .lock-lg {
    font-size: 34px;
  }

  .lock-sm {
    font-size: 28px;
  }

  .ev {
    font-size: 170px;
    line-height: 0.9;
    letter-spacing: 0.02em;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .stage {
    font-size: 96px;
    line-height: 1;
    letter-spacing: 0.03em;
    color: var(--color-gold);
  }

  .stage .kind {
    margin-left: 18px;
    font-size: 48px;
    letter-spacing: 0.12em;
    color: var(--color-text-secondary);
    vertical-align: middle;
  }

  .clock {
    display: flex;
    align-items: baseline;
    gap: 20px;
    margin-top: 6px;
  }

  .clock-label {
    font-family: var(--font-mono);
    font-size: 22px;
    font-weight: 400;
    letter-spacing: 0.2em;
    color: var(--color-text-disabled);
  }

  .clock-text {
    font-family: var(--font-mono);
    font-size: 72px;
    line-height: 1;
    letter-spacing: 0.02em;
    text-transform: none;
  }

  /* "Starting soon" or a day, words rather than digits. */
  .clock-text.words {
    font-family: var(--font-display);
    font-size: 64px;
    letter-spacing: 0.06em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  .brb {
    font-size: 200px;
    line-height: 0.9;
    letter-spacing: 0.03em;
  }

  .rule {
    width: 120px;
    height: 3px;
    background: var(--color-gold);
  }

  .where {
    font-size: 44px;
    letter-spacing: 0.08em;
  }

  .dot {
    margin: 0 16px;
    color: var(--color-text-secondary);
  }

  .gold {
    color: var(--color-gold);
  }

  .eyebrow {
    font-family: var(--font-mono);
    font-size: 18px;
    font-weight: 400;
    line-height: 1;
    letter-spacing: 0.16em;
    color: var(--color-text-disabled);
    white-space: pre;
  }

  /* One line, whatever the labels: a wrap would push the card past its
   * band, onto the topline and the race cards. */
  .headline {
    font-size: 40px;
    line-height: 1;
    letter-spacing: 0.16em;
    color: var(--color-text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  /* Two runners on a group, one on a final; a stage sending more on
   * (`advance` is the config's call) narrows the columns, the avatars
   * with them, rather than spilling out of the band. */
  .headliners {
    display: flex;
    justify-content: center;
    gap: 120px;
    width: 100%;
    margin-top: 8px;
  }

  .headliner {
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 14px;
    flex: 0 1 560px;
    min-width: 0;
  }

  .hav {
    width: 260px;
    max-width: 100%;
    aspect-ratio: 1 / 1;
    object-fit: cover;
    border: 3px solid var(--color-gold);
    box-sizing: border-box;
  }

  .hav-placeholder {
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface-elevated);
    color: var(--color-text-secondary);
    font-size: 120px;
  }

  .hn {
    max-width: 100%;
    font-size: 72px;
    line-height: 1;
    letter-spacing: 0.02em;
    text-transform: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .hl {
    display: flex;
    align-items: center;
    gap: 18px;
  }

  .hp {
    font-family: var(--font-mono);
    font-size: 44px;
    line-height: 1;
    color: var(--color-gold);
  }

  /* The standings panel's advancing chip, larger. Literal colour: OBS
   * builds in the field still ship Chromium 103, which predates
   * color-mix(). */
  .chip {
    font-family: var(--font-mono);
    font-size: 20px;
    font-weight: 400;
    letter-spacing: 0.14em;
    color: var(--color-gold);
    border: 1px solid rgba(200, 164, 78, 0.5);
    padding: 4px 10px;
  }
</style>
