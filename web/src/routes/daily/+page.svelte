<script lang="ts">
  // The +page.ts loader either redirects to /daily/{date} or surfaces this
  // empty state when the API has no daily for the current rotation.
</script>

<main class="daily-empty">
  <h1>No daily seed today</h1>
  <p>Check back after the next 08:00 UTC rotation.</p>
</main>

<style>
  .daily-empty {
    max-width: 600px;
    margin: 4rem auto;
    text-align: center;
    color: var(--color-text-secondary);
  }

  .daily-empty h1 {
    margin: 0 0 0.5rem;
    color: var(--color-gold);
  }
</style>
