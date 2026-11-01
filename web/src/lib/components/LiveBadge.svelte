<script lang="ts">
  interface Props {
    /** The stream; without one the badge is a plain mark (inside a link of its own). */
    href?: string;
    small?: boolean;
    onclick?: (e: MouseEvent) => void;
  }

  let { href, small = false, onclick }: Props = $props();
</script>

{#if href}
  <a
    {href}
    target="_blank"
    rel="noopener noreferrer"
    class="live-badge"
    class:small
    title="Watch live on Twitch"
    {onclick}>LIVE</a
  >
{:else}
  <span class="live-badge" class:small>LIVE</span>
{/if}

<style>
  .live-badge {
    font-size: 0.6rem;
    font-weight: 700;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    color: #fff;
    background: #e91916;
    padding: 0.1rem 0.35rem;
    border-radius: 3px;
    text-decoration: none;
    flex-shrink: 0;
    animation: pulse-live 2s ease-in-out infinite;
  }

  .live-badge.small {
    font-size: 0.55rem;
    padding: 0.05rem 0.3rem;
    border-radius: 2px;
    align-self: center;
  }

  @keyframes pulse-live {
    0%,
    100% {
      opacity: 1;
    }
    50% {
      opacity: 0.7;
    }
  }
</style>
