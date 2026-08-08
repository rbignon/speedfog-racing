<script lang="ts">
  import type { TrainingSession } from "$lib/api";
  import { formatPoolName } from "$lib/utils/format";
  import { formatIgt } from "$lib/utils/training";
  import { timeAgo } from "$lib/utils/time";

  let { session }: { session: TrainingSession } = $props();

  let routeState = $derived(
    session.status === "active"
      ? "playing"
      : session.status === "finished"
        ? "finished"
        : "setup",
  );
  let progress = $derived(
    session.status === "active" &&
      session.current_layer != null &&
      session.seed_total_layers
      ? Math.min(1, session.current_layer / session.seed_total_layers)
      : null,
  );
</script>

<a href="/training/{session.id}" class="card route-{routeState}">
  <div
    class="route route-{routeState}"
    class:route-progress={progress != null}
    style={progress != null ? `--route-progress: ${progress}` : null}
    aria-hidden="true"
  >
    <span class="line"></span>
    {#if progress != null}
      <span class="line-progress"></span>
      <span class="m-pos"></span>
    {/if}
    <span class="m-start"></span>
    {#if routeState !== "setup"}
      <span class="m-end"></span>
    {/if}
    {#if session.status === "active" && progress == null}
      <span class="m-train"></span>
    {/if}
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
    <span class="action-label">Resume &rarr;</span>
  </div>
</a>

<style>
  .card {
    position: relative;
    display: block;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    padding: 0.8rem 1.1rem 0.9rem;
    text-decoration: none;
    color: inherit;
    transition: border-color var(--transition);
  }

  /* Hover in the route line's hue (from the root's route-{state} class) */
  .card:hover {
    border-color: var(--route-color, var(--color-purple));
  }

  .card > :global(.route) {
    position: absolute;
    top: -7px;
    left: -7px;
    right: -7px;
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
