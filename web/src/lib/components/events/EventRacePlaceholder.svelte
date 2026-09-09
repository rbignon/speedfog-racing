<script lang="ts">
  /**
   * A stage race slot nothing is attached to yet: the race card's geometry
   * (route line as the top edge) with the setup dashes, no link.
   */
  let {
    name,
    note,
    partner,
  }: { name: string; note: string; partner: string | null } = $props();
</script>

<div class="card">
  <div class="route route-setup" aria-hidden="true">
    <span class="line"></span>
    <span class="m-start"></span>
    <span class="m-end"></span>
  </div>
  <div class="head">
    <span class="name">{name}</span>
    <span class="signal signal-setup">Upcoming</span>
  </div>
  <div class="foot">
    <span class="meta">{note}</span>
    <span class="byline">SpeedFog{partner ? ` × ${partner}` : ""}</span>
  </div>
</div>

<style>
  .card {
    position: relative;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    padding: 0.8rem 1.1rem 0.9rem;
    min-width: 0;
  }
  .card > :global(.route) {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
  }
  .head {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.75rem;
  }
  .name {
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }
  .foot {
    display: flex;
    justify-content: space-between;
    align-items: center;
    gap: 1rem;
    margin-top: 0.6rem;
  }
  .meta {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-disabled);
  }
  .byline {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }
</style>
