<script module lang="ts">
  /* One skull for the whole platform: data rows, the node popup and the
   * map's death animation all draw this 24x24 path (evenodd punches the
   * eyes, nose and teeth out of the silhouette). */
  export const SKULL_PATH =
    "M12 2C7.03 2 3.4 5.66 3.4 10.2c0 2.86 1.43 5.24 3.7 6.74l.5.33V20.5" +
    "c0 .83.67 1.5 1.5 1.5h5.8c.83 0 1.5-.67 1.5-1.5v-3.23l.5-.33" +
    "c2.27-1.5 3.7-3.88 3.7-6.74C20.6 5.66 16.97 2 12 2Z" +
    "M8.7 8.6a2.05 2.05 0 1 0 0 4.1 2.05 2.05 0 0 0 0-4.1Z" +
    "M15.3 8.6a2.05 2.05 0 1 0 0 4.1 2.05 2.05 0 0 0 0-4.1Z" +
    "M12 13.1l1.25 2.3h-2.5Z" +
    "M10.1 18.4h1.1v2.4h-1.1Z" +
    "M12.8 18.4h1.1v2.4h-1.1Z";
</script>

<script lang="ts">
  let { size = 11 }: { size?: number } = $props();
</script>

<svg viewBox="0 0 24 24" width={size} height={size} aria-hidden="true">
  <path d={SKULL_PATH} fill="currentColor" fill-rule="evenodd" />
</svg>

<style>
  svg {
    flex: none;
    vertical-align: -0.08em;
  }
</style>
