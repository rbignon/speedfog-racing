<script lang="ts">
  import { RUN_RULES } from "$lib/rules";

  // `title` null leaves the heading to a surrounding block that has its own.
  let { title = "Speedrun rules" }: { title?: string | null } = $props();
</script>

<div class="speedrun-rules">
  {#if title}
    <span class="rules-title">{title}</span>
  {/if}
  <ul>
    {#each RUN_RULES as rule (rule.lead)}
      <li>{rule.lead}{rule.rest}</li>
    {/each}
  </ul>
</div>

<style>
  .speedrun-rules {
    display: flex;
    flex-direction: column;
    gap: 0.3rem;
  }

  .rules-title {
    font-family: var(--font-mono);
    font-size: 0.7rem;
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
  }

  ul {
    margin: 0;
    padding-left: 1.2rem;
    line-height: 1.5;
  }
</style>
