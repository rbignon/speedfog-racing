<script lang="ts">
  import type { EventLadder, EventMode } from "$lib/api";
  import UserLink from "$lib/components/UserLink.svelte";

  let {
    ladder,
    modes,
    viewerId,
    spots = 0,
    emptyLabel = "No runs yet.",
  }: {
    ladder: EventLadder;
    modes: EventMode[];
    viewerId: string | null;
    /** Ladder positions the playoffs take; 0 hides the qualification cut. */
    spots?: number;
    /** What an empty ladder says; the page words it by phase. */
    emptyLabel?: string;
  } = $props();

  let search = $state("");
  let onlyNewcomers = $state(false);
  let onlyRanked = $state(false);

  let rows = $derived(
    ladder.entries.filter((e) => {
      if (onlyNewcomers && !e.newcomer) return false;
      if (onlyRanked && e.rank === null) return false;
      const q = search.trim().toLowerCase();
      if (!q) return true;
      return (
        e.user.twitch_username.toLowerCase().includes(q) ||
        (e.user.twitch_display_name ?? "").toLowerCase().includes(q)
      );
    }),
  );

  // Qualifying is positional, as seeding is (seed N takes the Nth ranked
  // entry): the first `spots` ranked rows, so a tie spanning the boundary
  // still cuts where the seats run out.
  let qualifying = $derived(
    new Set(
      ladder.entries
        .filter((e) => e.rank !== null)
        .slice(0, spots)
        .map((e) => e.user.id),
    ),
  );

  // The qualification cut sits under the last visible qualifying row, when a
  // row follows it.
  let cutIndex = $derived.by(() => {
    if (spots <= 0) return -1;
    let last = -1;
    rows.forEach((e, i) => {
      if (qualifying.has(e.user.id)) last = i;
    });
    return last >= 0 && last < rows.length - 1 ? last : -1;
  });
</script>

<div class="ladder">
  <div class="toolbar">
    <input
      class="search-input"
      type="search"
      placeholder="Find a runner"
      bind:value={search}
    />
    <div class="filter-chip-row">
      <button
        class="filter-chip"
        class:filter-chip-active={onlyNewcomers}
        aria-pressed={onlyNewcomers}
        onclick={() => (onlyNewcomers = !onlyNewcomers)}>Newcomers</button
      >
      <button
        class="filter-chip"
        class:filter-chip-active={onlyRanked}
        aria-pressed={onlyRanked}
        onclick={() => (onlyRanked = !onlyRanked)}>Ranked only</button
      >
    </div>
  </div>
  <div class="grid" style="--modes: {modes.length}">
    <div class="head">
      <span></span><span>Runner</span>
      {#each modes as mode (mode.key)}<span class="num">{mode.label}</span
        >{/each}
      <span class="num">Total</span>
    </div>
    {#if rows.length === 0}
      <p class="empty">
        {ladder.entries.length === 0
          ? emptyLabel
          : "No runner matches your filters."}
      </p>
    {:else}
      {#each rows as entry, i (entry.user.id)}
        <div
          class="row"
          class:me={viewerId !== null && entry.user.id === viewerId}
          class:withdrawn={entry.withdrawn || entry.forfeited}
          class:above-cut={i === cutIndex}
        >
          <span
            class="rank"
            class:rank-gold={entry.rank === 1}
            class:rank-silver={entry.rank === 2}
            class:rank-bronze={entry.rank === 3}
            >{entry.rank ?? (entry.withdrawn ? "" : "·")}</span
          >
          <div class="name-line">
            <UserLink user={entry.user} showBadge showAvatar />
            {#if entry.newcomer}<span class="newtag">newcomer</span>{/if}
            {#if entry.withdrawn}<span class="newtag">withdrawn</span>{/if}
            {#if entry.forfeited}<span class="newtag">forfeit</span>{/if}
          </div>
          {#each modes as mode (mode.key)}
            {@const p = entry.mode_points[mode.key]}
            <span class="cell" class:miss={p == null}
              >{p == null ? "·" : p}</span
            >
          {/each}
          {#if entry.total === null}
            <span
              class="cell miss"
              title="{entry.modes_scored} of {modes.length} modes scored"
              >{entry.modes_scored}/{modes.length}</span
            >
          {:else}
            <span class="cell total" class:prov={entry.provisional}
              >{entry.total}</span
            >
          {/if}
        </div>
        {#if i === cutIndex}
          <div class="cut" role="separator" aria-label="Qualification">
            Qualification
          </div>
        {/if}
      {/each}
    {/if}
  </div>
</div>

<style>
  .toolbar {
    display: flex;
    align-items: center;
    gap: 0.75rem;
    flex-wrap: wrap;
    margin-bottom: 0.6rem;
  }
  .search-input {
    flex: 1 1 220px;
    max-width: 320px;
    padding: 0.5rem 0.75rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-text);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
  }
  .search-input:focus {
    outline: none;
    border-color: var(--color-purple);
  }
  .filter-chip-row {
    display: flex;
    flex-wrap: wrap;
    gap: 0.5rem;
  }
  .filter-chip {
    background: transparent;
    border: 1px solid var(--color-border);
    color: var(--color-text-secondary);
    font-family: var(--font-family);
    font-size: var(--font-size-sm);
    font-weight: 500;
    padding: 0.35rem 0.85rem;
    border-radius: 999px;
    cursor: pointer;
    transition: all var(--transition);
  }
  .filter-chip:hover {
    border-color: var(--color-purple);
    color: var(--color-purple-hover);
  }
  .filter-chip-active,
  .filter-chip-active:hover {
    background: rgba(200, 164, 78, 0.15);
    border-color: var(--color-gold);
    color: var(--color-gold);
  }
  .empty {
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    color: var(--color-text-secondary);
    margin: 0 0 0.6rem;
  }
  .empty {
    margin: 0.85rem 0 0.2rem;
  }
  .grid {
    display: flex;
    flex-direction: column;
  }
  .head,
  .row {
    display: grid;
    grid-template-columns: 1.5rem minmax(0, 1fr) repeat(var(--modes), 64px) 84px;
    column-gap: 0.4rem;
    align-items: center;
  }
  .head {
    padding: 0 0 0.4rem;
    font-family: var(--font-mono);
    font-size: 0.65rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    border-bottom: 1px solid var(--color-border);
  }
  .row {
    padding: 0.75rem 0;
    border-bottom: 1px solid var(--color-border);
  }
  .row.me {
    background: rgba(200, 164, 78, 0.1);
    border-radius: var(--radius-sm);
  }
  /* The cut line stands in for the row border it follows. */
  .row.above-cut {
    border-bottom-color: transparent;
  }
  .cut {
    display: flex;
    align-items: center;
    gap: 0.6rem;
    color: var(--color-success);
    font-family: var(--font-mono);
    font-size: 0.6rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
  }
  .cut::before,
  .cut::after {
    content: "";
    flex: 1;
    border-top: 1px solid var(--color-success);
  }
  .num {
    text-align: right;
  }
  .rank {
    color: var(--color-text-secondary);
    font-family: var(--font-mono);
    font-weight: 600;
    text-align: right;
    padding-right: 0.25rem;
  }
  .rank-gold {
    color: var(--color-gold);
  }
  .rank-silver {
    color: #b8c5d6;
  }
  .rank-bronze {
    color: #d4a574;
  }
  .name-line {
    display: flex;
    align-items: center;
    gap: 0.4rem;
    min-width: 0;
  }
  /* Off the playoffs: the row stays on the ladder, receded, its tag kept
   * at full contrast since it is the only text saying why. */
  .row.withdrawn > .rank,
  .row.withdrawn > .cell,
  .row.withdrawn .name-line > :global(:first-child) {
    opacity: 0.55;
  }
  .newtag {
    font-family: var(--font-mono);
    font-size: 0.6rem;
    letter-spacing: 0.09em;
    text-transform: uppercase;
    color: var(--color-text-secondary);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 0 4px;
    white-space: nowrap;
    flex-shrink: 0;
  }
  .cell {
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    text-align: right;
    color: var(--color-text);
  }
  .cell.miss {
    color: var(--color-text-disabled);
  }
  .cell.total {
    color: var(--color-success);
    font-weight: 600;
  }
  .cell.total.prov {
    color: var(--color-gold);
  }
  @media (max-width: 640px) {
    .head,
    .row {
      grid-template-columns: 1.5rem minmax(0, 1fr) 84px;
    }
    .head > .num:not(:last-child),
    .row > .cell:not(:last-child) {
      display: none;
    }
  }
</style>
