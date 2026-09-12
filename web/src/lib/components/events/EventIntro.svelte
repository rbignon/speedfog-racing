<script lang="ts">
  import { auth } from "$lib/stores/auth.svelte";
  import { getTwitchLoginUrl } from "$lib/api";

  // A run montage: a silent loop beside the text and, once published, a
  // longer cut with sound on YouTube. While one is null the section goes
  // without it: the still stands in for the loop, and no link shows. The
  // still is also the loop's poster, so it should become the montage's first
  // frame once the loop lands.
  const LOOP_SRC = null as string | null;
  const FULL_RUN_URL = null as string | null;
  const STILL_SRC = "/screenshots/fog-gate.webp";

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
  <div class="text">
    <p class="lead">
      <strong>Elden Ring as a race, in about an hour.</strong>
      SpeedFog builds on thefifthmatt's
      <a
        href="https://www.nexusmods.com/eldenring/mods/3295"
        target="_blank"
        rel="noopener noreferrer">Fog Gate Randomizer</a
      >: every fog gate leads to a random zone, chained into a route that ends
      on a final boss drawn from the game's majors.
    </p>
    <dl class="concepts">
      <div>
        <dt>Pick your fog</dt>
        <dd>
          In most modes the route splits and merges. At each fork you choose a
          gate without knowing what lies behind it, and gates only go one way.
        </dd>
      </div>
      <div>
        <dt>Balanced paths</dt>
        <dd>
          Parallel branches are equally deep, equally hard, with the same number
          of bosses. Only the zones differ, so no route is a lucky one:
          knowledge and execution decide.
        </dd>
      </div>
      <div>
        <dt>No grind</dt>
        <dd>
          Items and enemies are shuffled, stat requirements are gone, and the
          weapons you find are upgraded to match your progress. Enemies get
          tougher the deeper you go.
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
      {#if LOOP_SRC}
        <video
          bind:this={video}
          src={LOOP_SRC}
          poster={STILL_SRC}
          muted
          loop
          playsinline
          preload={reducedMotion ? "none" : "auto"}
          aria-label="A SpeedFog run, cut and sped up"
          onplay={() => (paused = false)}
          onpause={() => (paused = true)}
        ></video>
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
      {:else}
        <img
          src={STILL_SRC}
          alt="A runner walking up to a fog gate"
          width="720"
          height="405"
        />
      {/if}
    </div>
    {#if FULL_RUN_URL}
      <figcaption>
        <a
          href={FULL_RUN_URL}
          class="more-link"
          target="_blank"
          rel="noopener noreferrer"
          aria-label="Watch a full run on YouTube (opens in new tab)"
          >Watch a full run on YouTube <span aria-hidden="true">&nearr;</span
          ></a
        >
      </figcaption>
    {/if}
  </figure>
</div>

<style>
  .intro {
    display: grid;
    grid-template-columns: minmax(0, 7fr) minmax(0, 5fr);
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
  .cta {
    display: flex;
    align-items: center;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .more-link {
    color: var(--color-text-secondary);
    text-decoration: none;
    font-size: var(--font-size-sm);
    transition: color 0.15s ease;
  }
  .more-link:hover {
    color: var(--color-purple);
  }
  .media {
    margin: 0;
    display: flex;
    flex-direction: column;
    align-items: flex-end;
    gap: 0.5rem;
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
  .frame video,
  .frame img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
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
