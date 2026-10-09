<script lang="ts">
  // A trailer as a muted loop that opens the full cut with sound on YouTube.
  // The poster is the loop's first frame, so playback starts on the image
  // already shown.
  let { src, poster, url }: { src: string; poster: string; url: string } =
    $props();

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

<figure class="media">
  <div class="frame">
    <!-- The play/pause button is a sibling, not a child, of the link:
         interactive content cannot nest in an anchor. -->
    <a
      class="watch"
      href={url}
      target="_blank"
      rel="noopener noreferrer"
      aria-label="Watch the trailer with sound on YouTube (opens in new tab)"
    >
      <video
        bind:this={video}
        {src}
        {poster}
        muted
        loop
        playsinline
        preload={reducedMotion ? "none" : "auto"}
        aria-hidden="true"
        onplay={() => (paused = false)}
        onpause={() => (paused = true)}
      ></video>
      <span class="chip hint" aria-hidden="true">Watch with sound &nearr;</span>
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

<style>
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
</style>
