<script lang="ts">
  import { auth } from "$lib/stores/auth.svelte";
  import { getTwitchLoginUrl } from "$lib/api";

  // The trailer: a muted loop beside the text, cut before its date card, that
  // opens the full cut with sound on YouTube. The still is the loop's poster
  // and its first frame, so playback starts on the image already shown.
  const LOOP_SRC = "/events/trailer.mp4";
  const TRAILER_URL = "https://youtu.be/V8ONFNyNgdA";
  const STILL_SRC = "/events/trailer-poster.webp";

  let video: HTMLVideoElement | undefined = $state();
  let reducedMotion = $state(false);
  // A viewer's own play or pause, which outranks the motion preference.
  let userPaused: boolean | null = $state(null);
  // Mirrors the element, so the button offers what a click will do even when
  // the browser refused to start the loop.
  let paused = $state(true);

  $effect(() => {
    const mql = window.matchMedia("(prefers-reduced-motion: reduce)");
    reducedMotion = mql.matches;
    const onChange = (e: MediaQueryListEvent) => (reducedMotion = e.matches);
    mql.addEventListener("change", onChange);
    return () => mql.removeEventListener("change", onChange);
  });

  // Played from here rather than through the autoplay attribute, so a viewer
  // who prefers reduced motion, even from a later switch, gets a still frame.
  $effect(() => {
    if (!video) return;
    if (userPaused ?? reducedMotion) video.pause();
    else video.play().catch(() => {});
  });

  function toggle() {
    if (!video) return;
    userPaused = !video.paused;
    if (userPaused) video.pause();
    else video.play().catch(() => {});
  }
</script>

<div class="intro">
  <p class="lead">
    <strong>Elden Ring as a race, in about an hour.</strong>
    SpeedFog builds on thefifthmatt's
    <a
      href="https://www.nexusmods.com/eldenring/mods/3295"
      target="_blank"
      rel="noopener noreferrer">Fog Gate Randomizer</a
    >: every fog gate leads to a random zone, chained into a route that ends on
    a final boss drawn from the game's majors.
  </p>
  <div class="text">
    <dl class="concepts">
      <div>
        <dt>Pick your fog</dt>
        <dd>
          The route <strong>splits and merges</strong>: at each fork you choose
          a gate without knowing what lies behind it.<br />Parallel branches are
          <strong>equally deep and equally hard</strong>, with the same number
          of bosses.
        </dd>
      </div>
      <div>
        <dt>Care package</dt>
        <dd>
          Every seed starts you with golden seeds, sacred tears, your
          <strong>Great Runes restored</strong>, and a care package of random
          spells, catalysts, talismans and armor, with your class weapon at
          <strong>maximum upgrade</strong>. Stat requirements are gone, so all
          of it is usable straight away.
        </dd>
      </div>
      <div>
        <dt>Dying doesn't matter, time does</dt>
        <dd>
          Enemies <strong>get tougher the deeper you go</strong>, but a death
          costs <strong>nothing but the time it takes to get back</strong>, so a
          risk is usually worth taking.
        </dd>
      </div>
    </dl>
    <!-- Signed out only: a reader who already has an account knows both what
         SpeedFog is and where to play it. Storing no redirect leaves the
         callback on its default, the dashboard, where a new account is walked
         through its first run. -->
    {#if !auth.user}
      <div class="cta">
        <a
          href={getTwitchLoginUrl()}
          class="btn btn-twitch"
          data-sveltekit-reload>Sign in to try a seed</a
        >
        <a href="/about" class="btn btn-secondary">How it works</a>
      </div>
    {/if}
  </div>
  <figure class="media">
    <div class="frame">
      <!-- The play/pause button is a sibling, not a child, of the link:
             interactive content cannot nest in an anchor. -->
      <a
        class="watch"
        href={TRAILER_URL}
        target="_blank"
        rel="noopener noreferrer"
        aria-label="Watch the trailer with sound on YouTube (opens in new tab)"
      >
        <video
          bind:this={video}
          src={LOOP_SRC}
          poster={STILL_SRC}
          muted
          loop
          playsinline
          preload={reducedMotion ? "none" : "auto"}
          aria-hidden="true"
          onplay={() => (paused = false)}
          onpause={() => (paused = true)}
        ></video>
        <span class="chip hint" aria-hidden="true"
          >Watch with sound &nearr;</span
        >
      </a>
      <button
        type="button"
        class="play-toggle"
        aria-label={paused ? "Play the video" : "Pause the video"}
        onclick={toggle}
      >
        <svg viewBox="0 0 16 16" aria-hidden="true">
          {#if paused}
            <path d="M5 3l8 5-8 5z" />
          {:else}
            <path d="M4 3h3v10H4zM9 3h3v10H9z" />
          {/if}
        </svg>
      </button>
    </div>
  </figure>
</div>

<style>
  .intro {
    display: grid;
    grid-template-columns: minmax(0, 1fr) minmax(0, 1fr);
    gap: 24px;
    align-items: start;
  }
  .text {
    max-width: 70ch;
    display: flex;
    flex-direction: column;
    align-items: flex-start;
    gap: 1rem;
  }
  .lead {
    grid-column: 1 / -1;
    margin: 0;
    color: var(--color-text-secondary);
  }
  .lead strong {
    color: var(--color-text);
  }
  .concepts {
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.8rem;
  }
  .concepts div {
    padding-left: 0.9rem;
    border-left: 2px solid var(--color-border);
  }
  .concepts dt {
    font-family: var(--font-display);
    font-size: 1rem;
    font-weight: 600;
    letter-spacing: 0.05em;
    text-transform: uppercase;
  }
  .concepts dd {
    margin: 0.15rem 0 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }
  .concepts dd strong {
    color: var(--color-text);
  }
  .cta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .media {
    margin: 0;
  }
  .frame {
    position: relative;
    width: 100%;
    aspect-ratio: 16 / 9;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow: hidden;
    background: var(--color-bg);
  }
  .frame video {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }
  .watch {
    display: block;
    height: 100%;
    border-radius: inherit;
  }
  /* Inset, since the frame clips anything drawn outside it. */
  .watch:focus-visible {
    outline: 2px solid var(--color-gold);
    outline-offset: -2px;
  }
  .hint {
    position: absolute;
    left: 0.6rem;
    bottom: 0.6rem;
    background: var(--color-surface);
    opacity: 0.85;
    transition:
      opacity 0.15s ease,
      color 0.15s ease;
  }
  .watch:hover .hint,
  .watch:focus-visible .hint {
    opacity: 1;
    color: var(--color-gold);
  }
  .play-toggle {
    position: absolute;
    right: 0.6rem;
    bottom: 0.6rem;
    width: 2rem;
    height: 2rem;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    border: 1px solid var(--color-border);
    border-radius: 50%;
    background: var(--color-surface);
    color: var(--color-text);
    opacity: 0.85;
    cursor: pointer;
    transition:
      opacity 0.15s ease,
      color 0.15s ease;
  }
  .play-toggle:hover,
  .play-toggle:focus-visible {
    opacity: 1;
    color: var(--color-gold);
  }
  .play-toggle svg {
    width: 0.8rem;
    height: 0.8rem;
    fill: currentColor;
  }
  @media (max-width: 900px) {
    .intro {
      grid-template-columns: 1fr;
    }
  }
</style>
