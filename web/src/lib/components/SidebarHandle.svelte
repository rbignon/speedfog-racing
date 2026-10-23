<script lang="ts">
  interface Props {
    collapsed: boolean;
    onToggle: () => void;
  }

  let { collapsed, onToggle }: Props = $props();

  let label = $derived(collapsed ? "Show sidebar" : "Hide sidebar");
</script>

<!-- Fold chevron of a left sidebar: in the right padding at mid-height while
     open, the whole band once folded. The sidebar must be `position:
     relative` and owns its folded layout: it hides every child except
     `.sidebar-handle`. -->
<button
  type="button"
  class="sidebar-handle"
  class:collapsed
  onclick={onToggle}
  title={label}
  aria-label={label}
>
  <svg
    width="14"
    height="14"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2.5"
    stroke-linecap="round"
    stroke-linejoin="round"
    aria-hidden="true"
  >
    {#if collapsed}
      <polyline points="9 6 15 12 9 18" />
    {:else}
      <polyline points="15 6 9 12 15 18" />
    {/if}
  </svg>
</button>

<style>
  .sidebar-handle {
    position: absolute;
    top: 50%;
    right: 2px;
    transform: translateY(-50%);
    z-index: 1;
    width: 20px;
    height: 44px;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: none;
    border: none;
    border-radius: var(--radius-sm);
    color: var(--color-text-secondary);
    cursor: pointer;
    transition: color var(--transition);
  }

  .sidebar-handle:hover {
    color: var(--color-text);
  }

  /* Drawn inside: the sidebar clips what crosses its edges. */
  .sidebar-handle:focus-visible {
    outline: 2px solid var(--color-purple);
    outline-offset: -2px;
  }

  /* The chevron stays on the right edge, so it follows the edge while the
     band slides, and ends centered in the 44px band. */
  .sidebar-handle.collapsed {
    inset: 0;
    width: auto;
    height: auto;
    transform: none;
    justify-content: flex-end;
    padding-right: 15px;
  }

  /* On mobile the sidebar stacks above the page: nothing to fold. */
  @media (max-width: 768px) {
    .sidebar-handle {
      display: none;
    }
  }
</style>
