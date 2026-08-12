<script lang="ts">
  import type { TrainingSession } from "$lib/api";
  import { formatPoolName } from "$lib/utils/format";
  import { formatIgt } from "$lib/utils/training";
  import { timeAgo } from "$lib/utils/time";

  let { session }: { session: TrainingSession } = $props();

  /* A solo run is always the viewer's own: whatever the status, the route
   * shows their brass progress over the grey line, the signal carries the
   * outcome (active / finished / DNF). */
  let progress = $derived(
    session.current_layer != null && session.seed_total_layers
      ? Math.min(1, session.current_layer / session.seed_total_layers)
      : 0,
  );
</script>

<a href="/training/{session.id}" class="card route-progress">
  <div
    class="route route-progress"
    style="--route-progress: {progress}"
    aria-hidden="true"
  >
    <span class="line"></span>
    <span class="line-progress"></span>
    <span class="m-pos"></span>
    <span class="m-start"></span>
    <span class="m-end"></span>
  </div>
  <div class="card-header">
    <span class="card-title"
      >{session.pool_display_name || formatPoolName(session.pool_name)}</span
    >
    <span class="signal signal-{session.status}"
      >{session.status === "abandoned" ? "DNF" : session.status}</span
    >
  </div>

  <div class="card-stats">
    <span class="stat">
      <span class="stat-label">IGT</span>
      <span class="stat-value">{formatIgt(session.igt_ms)}</span>
    </span>
    <span class="stat">
      <span class="stat-label">Deaths</span>
      <span class="stat-value">{session.death_count}</span>
    </span>
  </div>

  <div class="card-meta">
    <span>{timeAgo(session.created_at)}</span>
    <span class="action-label">Resume</span>
  </div>
</a>

<style>
  .card {
    position: relative;
    display: block;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    /* The route line IS the top edge (see RaceCard) */
    border-top-color: transparent;
    border-radius: var(--radius-lg);
    padding: 0.8rem 1.1rem 0.9rem;
    text-decoration: none;
    color: inherit;
    min-width: 0;
    transition: border-color var(--transition);
  }

  /* Hover in the route line's hue (from the root's route classes) */
  .card:hover {
    border-color: var(--route-color, var(--color-purple));
    border-top-color: transparent;
  }

  /* Same insets as RaceCard so markers align when both card kinds share
   * a grid (dashboard Active Now) */
  .card > :global(.route) {
    position: absolute;
    top: -7px;
    left: -10px;
    right: -10px;
  }

  .card-header {
    display: flex;
    justify-content: space-between;
    align-items: baseline;
    gap: 0.5rem;
    margin-bottom: 0.5rem;
  }

  .card-title {
    font-family: var(--font-display);
    font-size: 1.15rem;
    font-weight: 600;
    letter-spacing: 0.035em;
    text-transform: uppercase;
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .card-stats {
    display: flex;
    gap: 1.5rem;
    margin-bottom: 0.5rem;
  }

  .stat {
    display: flex;
    flex-direction: column;
    gap: 0.1rem;
  }

  .stat-label {
    font-family: var(--font-mono);
    font-size: 0.65rem;
    color: var(--color-text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.09em;
    font-weight: 500;
  }

  .stat-value {
    font-weight: 600;
    font-family: var(--font-mono);
  }

  .card-meta {
    display: flex;
    justify-content: space-between;
    align-items: center;
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
  }

  .action-label {
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    color: var(--color-purple);
    font-weight: 500;
  }
</style>
