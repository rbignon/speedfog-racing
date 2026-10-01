<script lang="ts">
  // Site-wide notice for a banned account: it can still sign in and browse,
  // so it is told why races, training, events and chat refuse it. Not
  // dismissible, since the ban stays until an admin lifts it.
  import { auth } from "$lib/stores/auth.svelte";
</script>

{#if auth.user?.banned_at}
  <div class="banned" role="alert" data-testid="banned-banner">
    <span class="banned-icon" aria-hidden="true">&#9888;</span>
    <p>Your account is banned: {auth.user.ban_reason}</p>
  </div>
{/if}

<style>
  .banned {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    padding: 0.65rem 2rem 0.65rem 1.5rem;
    background: rgba(220, 106, 81, 0.12);
    border-bottom: 1px solid rgba(220, 106, 81, 0.45);
  }

  .banned-icon {
    color: var(--color-danger);
    font-size: 1.2rem;
    flex-shrink: 0;
  }

  .banned p {
    margin: 0;
    flex: 1;
    color: var(--color-text);
    line-height: 1.5;
  }

  @media (max-width: 640px) {
    .banned {
      padding: 0.6rem 1rem;
      font-size: var(--font-size-sm);
    }
  }
</style>
