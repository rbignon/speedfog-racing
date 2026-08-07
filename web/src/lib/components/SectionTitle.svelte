<script lang="ts">
  import type { Snippet } from "svelte";

  let { children }: { children: Snippet } = $props();
</script>

<h2>
  <svg
    class="device"
    width="26"
    height="10"
    viewBox="0 0 26 10"
    aria-hidden="true"
  >
    <circle
      cx="5"
      cy="5"
      r="3.2"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
    />
    <line
      x1="10"
      y1="5"
      x2="26"
      y2="5"
      stroke="currentColor"
      stroke-width="2"
    />
  </svg>
  {@render children()}
</h2>

<style>
  h2 {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    margin: 0 0 1rem;
    font-family: var(--font-display);
    font-size: var(--font-size-lg);
    font-weight: 600;
    letter-spacing: 0.08em;
    text-transform: uppercase;
    color: var(--color-gold);
  }

  .device {
    flex: none;
  }
</style>
