<script lang="ts">
  interface Props {
    youtubeId: string;
    title: string;
    start?: number;
  }

  let { youtubeId, title, start = 0 }: Props = $props();

  const thumbnail = $derived(
    `https://i.ytimg.com/vi/${youtubeId}/hqdefault.jpg`,
  );
  const watchUrl = $derived(
    `https://www.youtube.com/watch?v=${youtubeId}${start ? `&t=${start}s` : ""}`,
  );
</script>

<a
  class="video-link"
  href={watchUrl}
  target="_blank"
  rel="noopener noreferrer"
  aria-label={`Watch on YouTube (opens in new tab): ${title}`}
>
  <img src={thumbnail} alt="" loading="lazy" />
  <span class="play-icon" aria-hidden="true"></span>
</a>

<style>
  .video-link {
    position: relative;
    display: block;
    width: 100%;
    aspect-ratio: 16 / 9;
    border-radius: var(--radius-sm);
    overflow: hidden;
    background: var(--color-bg);
  }

  .video-link img {
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

  .video-link:hover .play-icon {
    background: var(--color-gold-hover, #d4a520);
  }
</style>
