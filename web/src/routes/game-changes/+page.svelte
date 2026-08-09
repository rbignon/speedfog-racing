<script lang="ts">
  import { PUBLIC_BASE_URL } from "$env/static/public";
  import SectionTitle from "$lib/components/SectionTitle.svelte";
  import EmphasisText from "$lib/components/EmphasisText.svelte";
  import { CONTENT_ITEMS } from "$lib/content/items";
  import {
    CATEGORY_LABELS,
    GAME_CHANGE_CATEGORIES,
    type GameChangeCategory,
  } from "$lib/content/types";

  const sections = GAME_CHANGE_CATEGORIES.map(
    (category: GameChangeCategory) => ({
      category,
      label: CATEGORY_LABELS[category],
      items: CONTENT_ITEMS.filter(
        (i) => i.kind === "game_change" && i.category === category,
      ),
    }),
  ).filter((s) => s.items.length > 0);
</script>

<svelte:head>
  <title>Game Changes – SpeedFog Racing</title>
  <meta
    name="description"
    content="Everything SpeedFog changes compared to the base game: starting kit, fog gates, Torrent in boss arenas, opened gates, shops and more."
  />
  <link rel="canonical" href="{PUBLIC_BASE_URL}/game-changes" />
</svelte:head>

<main class="game-changes">
  <header class="game-changes-hero">
    <h1>Game Changes</h1>
    <p>
      SpeedFog modifies Elden Ring well beyond shuffling fog gates.<br>This page
      lists everything that differs from the base game.
    </p>
  </header>

  {#each sections as section}
    <section class="section" id={section.category}>
      <SectionTitle>{section.label}</SectionTitle>
      {#each section.items as item}
        <div class="change">
          <h3>{item.title}</h3>
          <p><EmphasisText text={item.body ?? item.short} /></p>
        </div>
      {/each}
    </section>
  {/each}
</main>

<style>
  .game-changes {
    max-width: 760px;
    width: 100%;
    box-sizing: border-box;
    margin: 0 auto;
    padding: 2rem;
  }

  /* Hero */
  .game-changes-hero {
    text-align: center;
    padding: 1.5rem 0 0.5rem;
  }

  .game-changes-hero h1 {
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--color-text);
    margin: 0 0 0.5rem;
  }

  .game-changes-hero p {
    color: var(--color-text-secondary);
    font-size: clamp(0.9rem, 2vw, 1.1rem);
    margin: 0;
  }

  /* Sections */
  .section {
    margin-top: 2.5rem;
  }

  .change {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-md);
    padding: 0.9rem 1.1rem;
    margin-bottom: 0.75rem;
  }

  .change h3 {
    margin: 0 0 0.3rem;
    color: var(--color-text);
  }

  .change p {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    line-height: 1.6;
  }

  @media (max-width: 640px) {
    .game-changes {
      padding: 1rem;
    }

    .section {
      margin-top: 2rem;
    }
  }
</style>
