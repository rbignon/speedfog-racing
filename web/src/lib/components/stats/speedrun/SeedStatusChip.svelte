<script lang="ts">
  import type { SpeedrunSeed } from "$lib/api";

  let {
    seed,
  }: {
    seed: Pick<
      SpeedrunSeed,
      "replayable" | "not_replayable_reason" | "kept_reasons"
    >;
  } = $props();

  const uid = $props.id();
  const tipId = `seed-status-${uid}`;
</script>

<!-- The reason is a tooltip, shown on hover and on keyboard focus: the chip
     takes focus so a keyboard reaches it. -->
<!-- svelte-ignore a11y_no_noninteractive_tabindex -->
<span class="seed-status" tabindex="0" aria-describedby={tipId}>
  <span
    class="signal"
    class:signal-open={seed.replayable}
    class:signal-abandoned={!seed.replayable}
    >{seed.replayable ? "Replayable" : "Not replayable"}</span
  >
  <span class="seed-tip" role="tooltip" id={tipId}>
    {#if !seed.replayable}
      {seed.not_replayable_reason}
    {:else if seed.kept_reasons.length > 0}
      <strong>Files kept</strong>
      <span class="kept">{seed.kept_reasons.join(" · ")}</span>
    {:else}
      Files may be purged. Protect this seed to keep them.
    {/if}
  </span>
</span>

<style>
  .seed-status {
    position: relative;
    display: inline-flex;
    align-items: center;
    cursor: help;
    border-radius: var(--radius-sm);
  }

  .seed-status .signal {
    text-decoration: underline dotted;
    text-underline-offset: 3px;
  }

  .seed-tip {
    display: none;
    position: absolute;
    top: calc(100% + 6px);
    right: 0;
    z-index: 20;
    width: max-content;
    max-width: min(22rem, 80vw);
    gap: 0.6rem;
    align-items: baseline;
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

  .seed-status:hover .seed-tip,
  .seed-status:focus-visible .seed-tip {
    display: flex;
  }

  .kept {
    color: var(--color-text-secondary);
  }
</style>
