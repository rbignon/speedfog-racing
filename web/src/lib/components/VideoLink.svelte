<script lang="ts">
  import type { ContentVideo } from "$lib/content/types";

  interface Props {
    video: ContentVideo;
    title: string;
  }

  let { video, title }: Props = $props();

  const link = $derived(
    video.twitchClipId !== undefined
      ? {
          site: "Twitch",
          thumbnail: video.thumbnail,
          url: `https://clips.twitch.tv/${video.twitchClipId}`,
        }
      : {
          site: "YouTube",
          thumbnail: `https://i.ytimg.com/vi/${video.youtubeId}/hqdefault.jpg`,
          url: `https://www.youtube.com/watch?v=${video.youtubeId}${video.start ? `&t=${video.start}s` : ""}`,
        },
  );
</script>

<a
  class="video-link"
  href={link.url}
  target="_blank"
  rel="noopener noreferrer"
  aria-label={`Watch on ${link.site} (opens in new tab): ${title}`}
>
  <img src={link.thumbnail} alt="" loading="lazy" />
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
