<script lang="ts">
  import { onMount } from "svelte";
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { PUBLIC_BASE_URL } from "$env/static/public";
  import { fetchZoneIndex, type ZoneIndexEntry } from "$lib/api";
  import { skipCountForZones } from "$lib/content/zones";
  import ZoneSheet from "$lib/components/ZoneSheet.svelte";

  let zones = $state<ZoneIndexEntry[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  let search = $state("");
  let filterLegacy = $state(false);
  let filterMinor = $state(false);
  let filterHasSkips = $state(false);

  onMount(() => {
    loadData();
  });

  async function loadData() {
    loading = true;
    error = null;
    try {
      const res = await fetchZoneIndex();
      zones = res.zones;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load zone codex.";
    } finally {
      loading = false;
    }
  }

  let filteredZones = $derived.by(() => {
    const query = search.trim().toLowerCase();
    const typeFilterActive = filterLegacy || filterMinor;
    return zones.filter((zone) => {
      if (query && !zone.display_name.toLowerCase().includes(query)) {
        return false;
      }
      if (typeFilterActive) {
        const matchesLegacy = filterLegacy && zone.type === "legacy_dungeon";
        const matchesMinor = filterMinor && zone.type === "mini_dungeon";
        if (!matchesLegacy && !matchesMinor) return false;
      }
      if (filterHasSkips && skipCountForZones(zone.zones) === 0) {
        return false;
      }
      return true;
    });
  });

  type ZoneSortKey =
    | "display_name"
    | "skips"
    | "visits"
    | "median_time_ms"
    | "fastest_time_ms"
    | "avg_deaths_per_visit"
    | "backtrack_rate";
  let sortKey = $state<ZoneSortKey>("display_name");
  let sortAsc = $state(true);

  function handleZoneSort(key: ZoneSortKey) {
    if (sortKey === key) {
      sortAsc = !sortAsc;
    } else {
      sortKey = key;
      // Zone name defaults ascending (A-Z) and Fastest too (quickest clears
      // first, the direction its name implies); other numeric columns default
      // descending (highest/slowest/deadliest first, the more useful read).
      sortAsc = key === "display_name" || key === "fastest_time_ms";
    }
  }

  function zoneSortIndicator(key: ZoneSortKey): string {
    if (sortKey !== key) return "";
    return sortAsc ? " ▲" : " ▼";
  }

  function zoneSortAria(key: ZoneSortKey): "ascending" | "descending" | "none" {
    if (sortKey !== key) return "none";
    return sortAsc ? "ascending" : "descending";
  }

  // Composes on top of filteredZones (search + type/skip filters), so
  // sorting never changes which rows are shown, only their order.
  let sortedZones = $derived.by(() => {
    const rows = filteredZones.map((zone) => ({
      zone,
      skips: skipCountForZones(zone.zones),
    }));
    rows.sort((a, b) => {
      // Zones visited but never cleared have median/fastest_time_ms 0,
      // rendered as "-": keep them last in both sort directions instead of
      // letting the 0 sentinel top the ascending order.
      if (sortKey === "median_time_ms" || sortKey === "fastest_time_ms") {
        const aMissing = a.zone[sortKey] === 0;
        const bMissing = b.zone[sortKey] === 0;
        if (aMissing !== bMissing) return aMissing ? 1 : -1;
      }
      let cmp: number;
      if (sortKey === "display_name") {
        cmp = a.zone.display_name.localeCompare(b.zone.display_name);
      } else if (sortKey === "skips") {
        cmp = a.skips - b.skips;
      } else {
        cmp = a.zone[sortKey] - b.zone[sortKey];
      }
      return sortAsc ? cmp : -cmp;
    });
    return rows;
  });

  // Deep-link contract: /zones?zone=<node_id> renders the index with the
  // drawer open on that zone. The race page and ZonesTab link here.
  let selectedNodeId = $derived(page.url.searchParams.get("zone"));
  let selectedZone = $derived(
    selectedNodeId
      ? (zones.find((zone) => zone.node_id === selectedNodeId) ?? null)
      : null,
  );

  // Move focus into the drawer when it opens (closed -> open transition
  // only, so switching between zones while it's already open doesn't yank
  // focus away from ZoneSheet's own content).
  let drawerEl: HTMLDivElement | undefined = $state();
  let drawerWasOpen = false;
  $effect(() => {
    if (selectedNodeId && !drawerWasOpen) {
      drawerEl?.focus();
    }
    drawerWasOpen = selectedNodeId !== null;
  });

  function openZone(e: MouseEvent, nodeId: string) {
    if (
      e.defaultPrevented ||
      e.button !== 0 ||
      e.metaKey ||
      e.ctrlKey ||
      e.shiftKey ||
      e.altKey
    ) {
      return;
    }
    e.preventDefault();
    goto(`/zones?zone=${nodeId}`, { noScroll: true });
  }

  function closeDrawer() {
    // replaceState so Back after an explicit close does not reopen the drawer.
    goto("/zones", { noScroll: true, replaceState: true });
  }

  function handleWindowKeydown(e: KeyboardEvent) {
    if (e.key === "Escape" && selectedNodeId) {
      closeDrawer();
    }
  }

  function typeBadgeClass(type: string): string {
    if (type === "legacy_dungeon") return "type-badge-legacy";
    return "type-badge-mini";
  }

  function typeLabel(type: string): string {
    if (type === "legacy_dungeon") return "Legacy";
    return "Minor";
  }

  function formatTime(ms: number): string {
    const totalSeconds = Math.round(ms / 1000);
    const minutes = Math.floor(totalSeconds / 60);
    const seconds = totalSeconds % 60;
    return `${minutes}:${seconds.toString().padStart(2, "0")}`;
  }
</script>

<svelte:window onkeydown={handleWindowKeydown} />

<svelte:head>
  <title>Zone Codex - SpeedFog Racing</title>
  <meta
    name="description"
    content="Every explorable zone in SpeedFog Racing, with visit counts, median clear time, deaths, backtrack rate, and documented skips."
  />
  <!-- Inert for crawlers today (the app runs with ssr=false); kept so the
       tags are already right if SSR/prerender is ever enabled. -->
  <link rel="canonical" href="{PUBLIC_BASE_URL}/zones" />
</svelte:head>

<main class="zones-page">
  <div class="page-header">
    <h1>Zone Codex</h1>
    <p class="subtitle">
      Aggregate stats for every explorable zone across the last 90 days.
    </p>
  </div>

  <div class="toolbar">
    <input
      type="text"
      class="search-input"
      placeholder="Search zones..."
      aria-label="Search zones"
      bind:value={search}
    />
    <div class="filter-chip-row">
      <button
        type="button"
        class="filter-chip"
        class:filter-chip-active={filterLegacy}
        aria-pressed={filterLegacy}
        onclick={() => (filterLegacy = !filterLegacy)}
      >
        Legacy
      </button>
      <button
        type="button"
        class="filter-chip"
        class:filter-chip-active={filterMinor}
        aria-pressed={filterMinor}
        onclick={() => (filterMinor = !filterMinor)}
      >
        Minor
      </button>
      <button
        type="button"
        class="filter-chip"
        class:filter-chip-active={filterHasSkips}
        aria-pressed={filterHasSkips}
        onclick={() => (filterHasSkips = !filterHasSkips)}
      >
        Has skips
      </button>
    </div>
  </div>

  {#if loading}
    <p class="status-text">Loading zone codex...</p>
  {:else if error}
    <p class="status-text error-text">{error}</p>
  {:else if zones.length === 0}
    <p class="status-text">No zone data recorded in the last 90 days.</p>
  {:else if filteredZones.length === 0}
    <p class="status-text">No zones match your filters.</p>
  {:else}
    <div class="zone-table-wrap">
      <div class="zone-table">
        <div class="zone-table-header">
          <span class="col-zone" aria-sort={zoneSortAria("display_name")}>
            <button
              type="button"
              class="sort-btn"
              onclick={() => handleZoneSort("display_name")}
            >
              Zone{zoneSortIndicator("display_name")}
            </button>
          </span>
          <span class="col-num" aria-sort={zoneSortAria("skips")}>
            <button
              type="button"
              class="sort-btn"
              onclick={() => handleZoneSort("skips")}
            >
              Skips{zoneSortIndicator("skips")}
            </button>
          </span>
          <span class="col-num" aria-sort={zoneSortAria("visits")}>
            <button
              type="button"
              class="sort-btn"
              onclick={() => handleZoneSort("visits")}
            >
              Visits{zoneSortIndicator("visits")}
            </button>
          </span>
          <span class="col-num" aria-sort={zoneSortAria("median_time_ms")}>
            <button
              type="button"
              class="sort-btn"
              onclick={() => handleZoneSort("median_time_ms")}
            >
              Median clear{zoneSortIndicator("median_time_ms")}
            </button>
          </span>
          <span class="col-num" aria-sort={zoneSortAria("fastest_time_ms")}>
            <button
              type="button"
              class="sort-btn"
              onclick={() => handleZoneSort("fastest_time_ms")}
            >
              Fastest{zoneSortIndicator("fastest_time_ms")}
            </button>
          </span>
          <span
            class="col-num"
            aria-sort={zoneSortAria("avg_deaths_per_visit")}
          >
            <button
              type="button"
              class="sort-btn"
              onclick={() => handleZoneSort("avg_deaths_per_visit")}
            >
              Avg deaths{zoneSortIndicator("avg_deaths_per_visit")}
            </button>
          </span>
          <span class="col-num" aria-sort={zoneSortAria("backtrack_rate")}>
            <button
              type="button"
              class="sort-btn"
              onclick={() => handleZoneSort("backtrack_rate")}
            >
              Backtrack{zoneSortIndicator("backtrack_rate")}
            </button>
          </span>
        </div>
        {#each sortedZones as { zone, skips } (zone.node_id)}
          <a
            href="/zones?zone={zone.node_id}"
            class="zone-row"
            onclick={(e) => openZone(e, zone.node_id)}
          >
            <span class="col-zone zone-name-cell">
              <span class="zone-name">{zone.display_name}</span>
              <span class="type-badge {typeBadgeClass(zone.type)}"
                >{typeLabel(zone.type)}</span
              >
            </span>
            <span class="col-num">{skips > 0 ? skips : "-"}</span>
            <!-- Raw count, 0 included: visits=0 is a real value (zone only
                 reached through warp landings), not a no-data sentinel like
                 median/fastest 0. -->
            <span class="col-num">{zone.visits}</span>
            <span class="col-num"
              >{zone.median_time_ms === 0
                ? "-"
                : formatTime(zone.median_time_ms)}</span
            >
            <span class="col-num"
              >{zone.fastest_time_ms === 0
                ? "-"
                : formatTime(zone.fastest_time_ms)}</span
            >
            <span class="col-num">{zone.avg_deaths_per_visit.toFixed(1)}</span>
            <!-- Share of visits ending in a turn-away, bounded to [0, 1]:
                 same percentage convention as ZonesTab's panel. -->
            <span class="col-num">{Math.round(zone.backtrack_rate * 100)}%</span
            >
          </a>
        {/each}
      </div>
    </div>
  {/if}
</main>

{#if selectedNodeId}
  <!-- svelte-ignore a11y_no_static_element_interactions -->
  <!-- svelte-ignore a11y_click_events_have_key_events -->
  <div class="drawer-scrim" onclick={closeDrawer}></div>
  <div
    class="drawer"
    role="dialog"
    aria-modal="true"
    aria-label="Zone details"
    tabindex="-1"
    bind:this={drawerEl}
  >
    <ZoneSheet
      nodeId={selectedNodeId}
      displayName={selectedZone?.display_name ?? null}
      zones={selectedZone?.zones ?? null}
      onClose={closeDrawer}
    />
  </div>
{/if}

<style>
  .zones-page {
    width: 100%;
    max-width: 1100px;
    margin: 0 auto;
    padding: 2rem;
    box-sizing: border-box;
  }

  .page-header {
    margin-bottom: 1.5rem;
  }

  .page-header h1 {
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--color-text);
    margin: 0 0 0.35rem 0;
  }

  .subtitle {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-base);
  }

  .toolbar {
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 0.75rem;
    margin-bottom: 1.25rem;
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

  .search-input::placeholder {
    color: var(--color-text-disabled);
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

  .filter-chip-active {
    background: rgba(200, 164, 78, 0.15);
    border-color: var(--color-gold);
    color: var(--color-gold);
  }

  .filter-chip-active:hover {
    border-color: var(--color-gold);
    color: var(--color-gold);
  }

  .status-text {
    color: var(--color-text-disabled);
    font-style: italic;
    padding: 2rem 0;
  }

  .error-text {
    color: var(--color-danger);
  }

  .zone-table-wrap {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow-x: auto;
  }

  .zone-table {
    min-width: 740px;
  }

  .zone-table-header,
  .zone-row {
    display: grid;
    grid-template-columns: minmax(180px, 2fr) 80px 80px 120px 100px 100px 100px;
    align-items: center;
    gap: 0.5rem;
    padding: 0.65rem 1rem;
  }

  .zone-table-header {
    color: var(--color-text-secondary);
    font-weight: 500;
    font-size: var(--font-size-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--color-border);
  }

  .sort-btn {
    background: none;
    border: none;
    color: inherit;
    font: inherit;
    text-transform: inherit;
    letter-spacing: inherit;
    cursor: pointer;
    padding: 0;
    transition: color var(--transition);
    white-space: nowrap;
  }

  .sort-btn:hover {
    color: var(--color-purple);
  }

  .zone-row {
    color: inherit;
    text-decoration: none;
    border-top: 1px solid var(--color-border);
    transition: background var(--transition);
  }

  .zone-row:first-of-type {
    border-top: none;
  }

  .zone-row:hover {
    background: var(--color-surface-elevated);
  }

  .zone-row:hover .zone-name {
    color: var(--color-purple);
  }

  .col-zone {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    overflow: hidden;
  }

  .zone-name-cell {
    min-width: 0;
  }

  .zone-name {
    font-weight: 500;
    font-size: var(--font-size-base);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
    transition: color var(--transition);
  }

  .col-num {
    text-align: right;
    font-family: var(--font-mono);
    font-size: var(--font-size-sm);
    color: var(--color-text-secondary);
  }

  .zone-table-header .col-num {
    text-align: right;
  }

  .type-badge {
    font-size: 0.65rem;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 0.05em;
    padding: 0.1rem 0.4rem;
    border-radius: var(--radius-sm);
    flex-shrink: 0;
  }

  .type-badge-legacy {
    background: rgba(200, 164, 78, 0.2);
    color: var(--color-gold);
  }

  .type-badge-mini {
    background: rgba(107, 114, 128, 0.2);
    color: var(--color-text-secondary);
  }

  .drawer-scrim {
    position: fixed;
    inset: 0;
    background: rgba(0, 0, 0, 0.6);
    z-index: 900;
  }

  .drawer {
    position: fixed;
    top: 0;
    right: 0;
    bottom: 0;
    height: 100vh;
    width: min(430px, 100%);
    background: var(--color-surface);
    border-left: 1px solid var(--color-border);
    box-shadow: -4px 0 20px rgba(0, 0, 0, 0.4);
    z-index: 901;
    overflow: hidden;
    outline: none;
  }

  @media (max-width: 640px) {
    .zones-page {
      padding: 1rem;
    }

    .toolbar {
      flex-direction: column;
      align-items: stretch;
    }

    .search-input {
      max-width: none;
    }

    .drawer {
      width: 100%;
    }
  }
</style>
