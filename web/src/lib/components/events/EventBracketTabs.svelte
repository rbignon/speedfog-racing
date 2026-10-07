<script lang="ts">
  import type { EventBracket, EventStage } from "$lib/api";

  let {
    brackets,
    stages,
    selected,
    onselect,
  }: {
    brackets: EventBracket[];
    stages: EventStage[];
    selected: string;
    onselect: (key: string) => void;
  } = $props();

  // The brackets with a race running carry the live dot, so a viewer on
  // another tab sees where the evening is.
  let live = $derived(
    stages
      .filter((s) => s.races.some((r) => r.race.status === "running"))
      .map((s) => s.bracket),
  );
</script>

<div class="tab-bar" role="tablist" aria-label="Brackets">
  {#each brackets as bracket (bracket.key)}
    <button
      type="button"
      role="tab"
      class="tab-btn"
      class:tab-active={selected === bracket.key}
      aria-selected={selected === bracket.key}
      onclick={() => onselect(bracket.key)}
    >
      {bracket.label}
      {#if live.includes(bracket.key)}<span class="live-dot" aria-label="Live"
        ></span>{/if}
    </button>
  {/each}
</div>

<style>
  .tab-bar {
    display: flex;
    flex-wrap: wrap;
    border-bottom: 1px solid var(--color-border);
  }
  .tab-btn {
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--color-text-secondary);
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    font-weight: 500;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    padding: 0.65rem 1.25rem;
    cursor: pointer;
    transition: all var(--transition);
  }
  .tab-btn:hover {
    color: var(--color-purple);
  }
  .tab-active,
  .tab-active:hover {
    color: var(--color-text);
    border-bottom-color: var(--color-gold);
  }
  .live-dot {
    display: inline-block;
    width: 7px;
    height: 7px;
    margin-left: 0.45rem;
    border-radius: 50%;
    background: var(--color-danger);
    vertical-align: middle;
  }
</style>
