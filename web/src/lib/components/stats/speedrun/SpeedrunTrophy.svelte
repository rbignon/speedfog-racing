<script lang="ts">
  let { place }: { place: number } = $props();
</script>

<svg
  class="sr-trophy"
  class:gold={place === 1}
  class:silver={place === 2}
  class:bronze={place === 3}
  viewBox="0 0 24 24"
  width="14"
  height="14"
  role="img"
  aria-label="Place {place}"
>
  <path
    fill="currentColor"
    d="M6 2h12v2h3v3a5 5 0 0 1-4.6 5A6 6 0 0 1 13 15.9V18h3v2H8v-2h3v-2.1A6 6 0 0 1 7.6 12 5 5 0 0 1 3 7V4h3V2Zm0 4H5v1a3 3 0 0 0 1.2 2.4A6 6 0 0 1 6 8V6Zm12 0v2c0 .5 0 1-.2 1.4A3 3 0 0 0 19 7V6h-1ZM6 21h12v1H6v-1Z"
  />
</svg>

<style>
  .sr-trophy {
    display: block;
    flex-shrink: 0;
  }

  .gold {
    color: var(--color-gold);
  }

  .silver {
    color: var(--color-text-secondary);
  }

  .bronze {
    color: var(--color-danger-dark);
  }
</style>
