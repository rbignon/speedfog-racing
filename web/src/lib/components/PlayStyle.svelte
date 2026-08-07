<script lang="ts">
  import type { UserTraitsResponse } from "$lib/api";

  interface TraitMeta {
    key: string;
    label: string;
    color: string;
    icon: string;
    description: string;
  }

  const TRAIT_META: TraitMeta[] = [
    {
      key: "rusher",
      label: "Rusher",
      color: "#EF4444",
      icon: "\u26A1",
      description: "Finishes fast, takes more deaths",
    },
    {
      key: "cautious",
      label: "Cautious",
      color: "#10B981",
      icon: "\uD83D\uDEE1",
      description: "Low deaths, plays it safe",
    },
    {
      key: "boss_slayer",
      label: "Boss Slayer",
      color: "#FBBF24",
      icon: "\u2694",
      description: "Fewer deaths on hard bosses",
    },
    {
      key: "resilient",
      label: "Resilient",
      color: "#C8A44E",
      icon: "\uD83D\uDCAA",
      description: "Finishes despite being behind",
    },
    {
      key: "explorer",
      label: "Explorer",
      color: "#3B82F6",
      icon: "\uD83C\uDF10",
      description: "Visits many nodes, backtracks",
    },
    {
      key: "pathfinder",
      label: "Pathfinder",
      color: "#A78BFA",
      icon: "\uD83E\uDDED",
      description: "Takes unique paths",
    },
    {
      key: "rage_quitter",
      label: "Rage Quitter",
      color: "#DC2626",
      icon: "\uD83D\uDCA5",
      description: "High abandon rate",
    },
  ];

  let { traits }: { traits: UserTraitsResponse } = $props();

  let dominantMeta = $derived(
    traits.dominant_trait
      ? TRAIT_META.find((t) => t.key === traits.dominant_trait)
      : null,
  );

  let sortedTraits = $derived(() => {
    if (!traits.scores) return [];
    return TRAIT_META.map((t) => ({
      ...t,
      score: traits.scores![t.key as keyof typeof traits.scores] ?? 0,
    })).sort((a, b) => b.score - a.score);
  });

  let maxScore = $derived(() => {
    if (!traits.scores) return 1;
    return Math.max(1, ...Object.values(traits.scores));
  });
</script>

{#if traits.scores}
  <div class="playstyle">
    <div class="dominant-trait">
      {#if dominantMeta}
        <span class="dominant-icon">{dominantMeta.icon}</span>
        <div class="dominant-info">
          <span class="dominant-name" style="color: {dominantMeta.color}"
            >{dominantMeta.label}</span
          >
          {#if traits.dominant_description}
            <span class="dominant-description"
              >{traits.dominant_description}</span
            >
          {/if}
          <span class="dominant-description">{dominantMeta.description}</span>
        </div>
      {:else}
        <span class="no-dominant">No dominant trait yet</span>
      {/if}
    </div>

    <div class="trait-bars-grid">
      {#each sortedTraits() as trait}
        <div class="trait-row" title={trait.description}>
          <span class="trait-icon">{trait.icon}</span>
          <span class="trait-label" style="color: {trait.color}"
            >{trait.label}</span
          >
          <div class="trait-track">
            <div
              class="trait-fill"
              style="width: {Math.max(
                4,
                (trait.score / maxScore()) * 100,
              )}%; background: {trait.color}"
            ></div>
          </div>
          <span class="trait-score">{trait.score.toFixed(0)}</span>
        </div>
      {/each}
    </div>
  </div>
{:else}
  <p class="traits-progress">
    {traits.finished_races} / {traits.races_required} races finished. Complete more
    races to unlock your play style profile.
  </p>
{/if}

<style>
  .playstyle {
    display: flex;
    flex-direction: column;
    gap: 1.25rem;
  }

  .dominant-trait {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    min-width: 0;
  }

  .dominant-icon {
    font-size: 1.75rem;
    flex-shrink: 0;
  }

  .dominant-info {
    display: flex;
    flex-direction: column;
    gap: 0.15rem;
    min-width: 0;
  }

  .dominant-name {
    font-size: var(--font-size-lg);
    font-weight: 700;
  }

  .dominant-description {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .no-dominant {
    font-size: var(--font-size-sm);
    color: var(--color-text-disabled);
    font-style: italic;
  }

  .trait-bars-grid {
    display: grid;
    grid-template-columns: 1fr 1fr;
    gap: 0.5rem 1.5rem;
  }

  .trait-row {
    display: grid;
    grid-template-columns: 1.4rem 6rem 1fr 2.5rem;
    align-items: center;
    gap: 0.4rem;
  }

  .trait-icon {
    font-size: 0.9rem;
    text-align: center;
  }

  .trait-label {
    font-size: var(--font-size-xs);
    font-weight: 600;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  .trait-track {
    background: var(--color-surface-elevated);
    border-radius: 4px;
    height: 8px;
    overflow: hidden;
  }

  .trait-fill {
    height: 8px;
    border-radius: 4px;
    transition: width 0.3s ease;
  }

  .trait-score {
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    font-family: var(--font-mono);
    text-align: right;
  }

  .traits-progress {
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
    font-style: italic;
    margin: 0;
  }

  @media (max-width: 560px) {
    .trait-bars-grid {
      grid-template-columns: 1fr;
    }
  }
</style>
