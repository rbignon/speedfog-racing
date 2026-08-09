<script lang="ts">
  import { PUBLIC_BASE_URL } from "$env/static/public";
  import changelogRaw from "../../../../CHANGELOG.md?raw";

  interface ChangelogItem {
    text: string;
    children: string[];
  }

  interface ChangelogEntry {
    version: string;
    date: string;
    sections: { title: string; items: ChangelogItem[] }[];
  }

  function parseChangelog(raw: string): ChangelogEntry[] {
    const entries: ChangelogEntry[] = [];
    let current: ChangelogEntry | null = null;
    let currentSection: { title: string; items: ChangelogItem[] } | null = null;

    for (const line of raw.split("\n")) {
      const versionMatch = line.match(/^## \[(.+?)\] - (.+)$/);
      if (versionMatch) {
        if (current) entries.push(current);
        current = {
          version: versionMatch[1],
          date: versionMatch[2],
          sections: [],
        };
        currentSection = null;
        continue;
      }

      if (!current) continue;

      const sectionMatch = line.match(/^### (.+)$/);
      if (sectionMatch) {
        currentSection = { title: sectionMatch[1], items: [] };
        current.sections.push(currentSection);
        continue;
      }

      const itemMatch = line.match(/^- (.+)$/);
      if (itemMatch && currentSection) {
        currentSection.items.push({ text: itemMatch[1], children: [] });
        continue;
      }

      const continuationMatch = line.match(/^ {2}- (.+)$/);
      if (
        continuationMatch &&
        currentSection &&
        currentSection.items.length > 0
      ) {
        currentSection.items[currentSection.items.length - 1].children.push(
          continuationMatch[1],
        );
      }
    }
    if (current) entries.push(current);

    return entries;
  }

  const entries = parseChangelog(changelogRaw);

  function formatItem(text: string): string {
    return text
      .replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>")
      .replace(/`(.+?)`/g, "<code>$1</code>")
      .replace(
        /\[(.+?)\]\(((https?:\/\/|\/)[^)]+)\)/g,
        '<a href="$2" target="_blank" rel="noopener noreferrer">$1</a>',
      );
  }
</script>

<svelte:head>
  <title>Changelog – SpeedFog Racing</title>
  <meta
    name="description"
    content="Latest updates and changes to SpeedFog Racing. New features, bug fixes, and improvements."
  />
  <link rel="canonical" href="{PUBLIC_BASE_URL}/changelog" />
</svelte:head>

<main class="changelog">
  <header class="changelog-hero">
    <h1>Changelog</h1>
    <p class="source-links">
      Sources:
      <a
        href="https://github.com/rbignon/speedfog"
        target="_blank"
        rel="noopener noreferrer">speedfog</a
      >
      ·
      <a
        href="https://github.com/rbignon/speedfog-racing"
        target="_blank"
        rel="noopener noreferrer">speedfog-racing</a
      >
    </p>
  </header>

  {#each entries as entry, i}
    <section class="version">
      <div class="version-header">
        <h2>
          {entry.version}
        </h2>
        <time datetime={entry.date}>{entry.date}</time>
      </div>

      {#each entry.sections as section}
        <h3>{section.title}</h3>
        <ul>
          {#each section.items as item}
            <li>
              {@html formatItem(item.text)}
              {#if item.children.length > 0}
                <ul>
                  {#each item.children as child}
                    <li>{@html formatItem(child)}</li>
                  {/each}
                </ul>
              {/if}
            </li>
          {/each}
        </ul>
      {/each}
    </section>
  {/each}
</main>

<style>
  .changelog {
    max-width: 760px;
    width: 100%;
    box-sizing: border-box;
    margin: 0 auto;
    padding: 2rem;
  }

  .changelog-hero {
    text-align: center;
    padding: 1.5rem 0 0.5rem;
  }

  .changelog-hero h1 {
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--color-text);
    margin: 0 0 0.5rem;
  }

  .changelog-hero p {
    color: var(--color-text-secondary);
    font-size: clamp(0.9rem, 2vw, 1.1rem);
    margin: 0;
  }

  .changelog-hero .source-links {
    margin-top: 0.5rem;
    font-size: var(--font-size-sm);
    color: var(--color-text-disabled);
  }

  .changelog-hero .source-links a {
    color: var(--color-purple);
    text-decoration: none;
  }

  .changelog-hero .source-links a:hover {
    text-decoration: underline;
  }

  .version {
    margin-top: 2.5rem;
    padding-bottom: 2rem;
    border-bottom: 1px solid var(--color-border);
  }

  .version:last-child {
    border-bottom: none;
  }

  .version-header {
    display: flex;
    align-items: baseline;
    justify-content: space-between;
    gap: 1rem;
    margin-bottom: 0.75rem;
  }

  /* Version numbers and dates are data: they run through the mono face */
  .version-header h2 {
    font-family: var(--font-mono);
    font-size: var(--font-size-xl);
    font-weight: 600;
    color: var(--color-gold);
    margin: 0;
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .version-header time {
    font-family: var(--font-mono);
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    white-space: nowrap;
  }

  .version h3 {
    color: var(--color-text);
    margin: 1.25rem 0 0.4rem;
  }

  .version h3:first-of-type {
    margin-top: 0;
  }

  .version ul {
    margin: 0 0 0.5rem;
    padding-left: 1.5rem;
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    line-height: 1.7;
  }

  .version li {
    margin-bottom: 0.25rem;
  }

  .version li :global(strong) {
    color: var(--color-text);
  }

  .version li :global(code) {
    background: var(--color-surface-elevated);
    padding: 0.1rem 0.35rem;
    border-radius: var(--radius-sm);
    font-size: 0.85em;
    color: var(--color-gold);
  }

  .version li :global(a) {
    color: var(--color-purple);
    text-decoration: none;
  }

  .version li :global(a:hover) {
    text-decoration: underline;
  }

  @media (max-width: 640px) {
    .changelog {
      padding: 1rem;
    }

    .version-header {
      flex-direction: column;
      gap: 0.25rem;
    }
  }
</style>
