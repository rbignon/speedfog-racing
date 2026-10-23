<script lang="ts">
  interface Props {
    collapsed: boolean;
    onToggle: () => void;
  }

  let { collapsed, onToggle }: Props = $props();

  let label = $derived(collapsed ? "Show sidebar" : "Hide sidebar");
</script>

<!-- Tab hanging off the right edge of a left sidebar, at mid-height. The
     sidebar must be `position: relative` and owns its collapsed layout:
     when collapsed it hides every child except `.sidebar-handle`. -->
<button
  type="button"
  class="sidebar-handle"
  onclick={onToggle}
  title={label}
  aria-label={label}
>
  <svg
    width="12"
    height="12"
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
  /* Starts on the sidebar's border and covers it, so the tab reads as part
     of the rail rather than a button floating over the page. */
  .sidebar-handle {
    position: absolute;
    top: 50%;
    right: -16px;
    transform: translateY(-50%);
    z-index: 2;
    width: 16px;
    height: 44px;
    padding: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-left: none;
    border-radius: 0 var(--radius-sm) var(--radius-sm) 0;
    color: var(--color-text-secondary);
    cursor: pointer;
    transition:
      color var(--transition),
      background var(--transition);
  }

  .sidebar-handle:hover {
    color: var(--color-text);
    background: var(--color-surface-elevated);
  }

  /* On mobile the sidebar stacks above the page: nothing to collapse. */
  @media (max-width: 768px) {
    .sidebar-handle {
      display: none;
    }
  }
</style>
