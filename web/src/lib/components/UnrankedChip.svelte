<script lang="ts">
  let { reason }: { reason: string } = $props();

  const uid = $props.id();
  const tipId = `unranked-${uid}`;
</script>

<!-- The reason is a tooltip, shown on hover and on focus (a tap focuses the
     chip on a phone; Escape blurs it): the chip takes focus so a keyboard
     reaches it. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex, a11y_no_static_element_interactions -->
<span
  class="unranked-status"
  tabindex="0"
  aria-describedby={tipId}
  onkeydown={(e) => {
    if (e.key === "Escape") e.currentTarget.blur();
  }}
>
  <span class="chip unranked-chip">Unranked</span>
  <span class="unranked-tip" role="tooltip" id={tipId}>{reason}</span>
</span>

<style>
  .unranked-status {
    position: relative;
    display: inline-flex;
    align-items: center;
    cursor: help;
    border-radius: var(--radius-sm);
  }

  .unranked-chip {
    padding: 0.1rem 0.4rem;
    font-size: 0.62rem;
    color: var(--color-text-secondary);
    border-color: color-mix(
      in srgb,
      var(--color-text-secondary) 60%,
      transparent
    );
  }

  .unranked-tip {
    display: none;
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 20;
    width: max-content;
    max-width: min(22rem, 80vw);
    padding: 0.45rem 0.6rem;
    background: var(--color-surface-elevated);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    font-family: var(--font-family);
    font-size: var(--font-size-xs);
    color: var(--color-text);
    letter-spacing: normal;
    text-transform: none;
    white-space: normal;
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.4);
  }

  .unranked-status:hover .unranked-tip,
  .unranked-status:focus .unranked-tip {
    display: block;
  }
</style>
