<script lang="ts">
  interface Props {
    label: string;
    busy?: boolean;
    error?: string | null;
    onclick: () => void;
  }

  let { label, busy = false, error = null, onclick }: Props = $props();
</script>

<!-- Takes the slot the race map will occupy once the viewer is in, so the empty
     slot teases the map instead of reading as a dead block. -->
<div class="dag-placeholder play-now-cta">
  <svg
    class="play-now-ghost"
    viewBox="0 0 880 400"
    preserveAspectRatio="xMidYMid slice"
    aria-hidden="true"
  >
    <g
      fill="none"
      stroke-width="7"
      stroke-linecap="round"
      stroke-linejoin="round"
    >
      <path d="M70 200 H810" style="stroke: var(--color-purple)" />
      <path d="M250 200 L330 100 H560" style="stroke: var(--color-gold)" />
      <path d="M600 200 L680 310 H814" style="stroke: var(--color-success)" />
    </g>
    <g fill="#cdd6e4">
      <circle cx="70" cy="200" r="10" />
      <circle cx="250" cy="200" r="10" />
      <circle cx="430" cy="200" r="10" />
      <circle cx="600" cy="200" r="10" />
      <circle cx="780" cy="200" r="10" />
      <circle cx="560" cy="100" r="10" />
      <circle cx="814" cy="310" r="10" />
    </g>
  </svg>
  <div class="play-now-glow" aria-hidden="true"></div>
  <div class="play-now-stack">
    <button class="btn btn-primary btn-lg" {onclick} disabled={busy}>
      {busy ? "Joining..." : label}
    </button>
    <span class="play-now-help">Your race map appears here</span>
    {#if error}
      <span class="play-now-error" role="alert">{error}</span>
    {/if}
  </div>
</div>

<style>
  /* Same box the pages give the DAG slot, so the CTA sits exactly where the
	   map will be. */
  .dag-placeholder {
    background: var(--color-surface);
    border: 2px dashed var(--color-border);
    border-radius: var(--radius-lg);
    display: flex;
    align-items: center;
    justify-content: center;
    min-height: 400px;
  }

  /* Over that box, a faint stylized "ghost DAG" silhouette and a gold glow sit
	   behind a real centered button. */
  .play-now-cta {
    position: relative;
    overflow: hidden;
    border: 1px solid var(--color-border);
  }

  .play-now-ghost {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
    opacity: 0.16;
  }

  .play-now-glow {
    position: absolute;
    inset: 0;
    background: radial-gradient(
      circle at 50% 50%,
      rgba(200, 164, 78, 0.12),
      transparent 50%
    );
  }

  .play-now-stack {
    position: relative;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 0.875rem;
    text-align: center;
  }

  .play-now-help {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .play-now-error {
    font-size: var(--font-size-sm);
    font-weight: 400;
    color: var(--color-danger);
  }
</style>
