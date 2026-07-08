<script lang="ts">
  interface Props {
    youtubeId: string;
    title: string;
    start?: number;
  }

  let { youtubeId, title, start = 0 }: Props = $props();

  let playing = $state(false);

  const thumbnail = $derived(
    `https://i.ytimg.com/vi/${youtubeId}/hqdefault.jpg`,
  );
  const embedUrl = $derived(
    `https://www.youtube-nocookie.com/embed/${youtubeId}?autoplay=1${start ? `&start=${start}` : ""}`,
  );
</script>

<div class="video-embed">
  {#if playing}
    <iframe
      src={embedUrl}
      {title}
      allow="autoplay; encrypted-media; picture-in-picture"
      allowfullscreen
    ></iframe>
  {:else}
    <button
      class="facade"
      onclick={() => (playing = true)}
      aria-label={`Play video: ${title}`}
    >
      <img src={thumbnail} alt="" loading="lazy" />
      <span class="play-icon" aria-hidden="true"></span>
    </button>
  {/if}
</div>

<style>
  .video-embed {
    position: relative;
    width: 100%;
    aspect-ratio: 16 / 9;
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--color-bg);
  }

  iframe {
    width: 100%;
    height: 100%;
    border: 0;
  }

  .facade {
    width: 100%;
    height: 100%;
    padding: 0;
    border: none;
    background: none;
    cursor: pointer;
    display: block;
    position: relative;
  }

  .facade img {
    width: 100%;
    height: 100%;
    object-fit: cover;
    display: block;
  }

  .play-icon {
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-50%, -50%);
    width: 3rem;
    height: 2.1rem;
    background: var(--color-gold);
    border-radius: var(--radius-sm);
  }

  .play-icon::after {
    content: "";
    position: absolute;
    top: 50%;
    left: 50%;
    transform: translate(-40%, -50%);
    border-style: solid;
    border-width: 0.45rem 0 0.45rem 0.75rem;
    border-color: transparent transparent transparent var(--color-bg);
  }

  .facade:hover .play-icon {
    background: var(--color-gold-hover, #d4a520);
  }
</style>
