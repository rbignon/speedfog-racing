<script lang="ts">
  import { page } from "$app/state";
  import { goto } from "$app/navigation";
  import { SvelteSet } from "svelte/reactivity";
  import OverviewTab from "$lib/components/stats/OverviewTab.svelte";
  import ZonesTab from "$lib/components/stats/ZonesTab.svelte";
  import BossesTab from "$lib/components/stats/BossesTab.svelte";
  import PlayersTab from "$lib/components/stats/PlayersTab.svelte";
  import WeaponsTab from "$lib/components/stats/WeaponsTab.svelte";

  type TabId = "overview" | "zones" | "bosses" | "players" | "weapons";

  const TABS: { id: TabId; label: string }[] = [
    { id: "overview", label: "Overview" },
    { id: "zones", label: "Zones" },
    { id: "bosses", label: "Major Bosses" },
    { id: "players", label: "Play Styles" },
    { id: "weapons", label: "Weapons" },
  ];

  let activeTab: TabId = $derived.by(() => {
    const param = page.url.searchParams.get("tab");
    if (param && TABS.some((t) => t.id === param)) return param as TabId;
    return "overview";
  });

  function switchTab(tab: TabId) {
    const url = new URL(page.url);
    if (tab === "overview") {
      url.searchParams.delete("tab");
    } else {
      url.searchParams.set("tab", tab);
    }
    goto(url.toString(), { replaceState: true, noScroll: true });
  }

  // Track which tabs have been activated for lazy loading
  let mountedTabs = new SvelteSet<TabId>(["overview"]);

  $effect(() => {
    mountedTabs.add(activeTab);
  });
</script>

<svelte:head>
  <title>Community Stats - SpeedFog Racing</title>
</svelte:head>

<main class="stats-page">
  <div class="page-header">
    <h1>Community Stats</h1>
    <p class="subtitle">
      Community activity, zone data, boss encounters, and player profiles across
      all races.
    </p>
  </div>

  <div class="tab-bar">
    {#each TABS as tab}
      <button
        class="tab-btn"
        class:tab-active={activeTab === tab.id}
        onclick={() => switchTab(tab.id)}
      >
        {tab.label}
      </button>
    {/each}
  </div>

  <div class="tab-content">
    {#if mountedTabs.has("overview")}
      <div class="tab-panel" class:tab-hidden={activeTab !== "overview"}>
        <OverviewTab />
      </div>
    {/if}
    {#if mountedTabs.has("zones")}
      <div class="tab-panel" class:tab-hidden={activeTab !== "zones"}>
        <ZonesTab />
      </div>
    {/if}
    {#if mountedTabs.has("bosses")}
      <div class="tab-panel" class:tab-hidden={activeTab !== "bosses"}>
        <BossesTab />
      </div>
    {/if}
    {#if mountedTabs.has("players")}
      <div class="tab-panel" class:tab-hidden={activeTab !== "players"}>
        <PlayersTab />
      </div>
    {/if}
    {#if mountedTabs.has("weapons")}
      <div class="tab-panel" class:tab-hidden={activeTab !== "weapons"}>
        <WeaponsTab />
      </div>
    {/if}
  </div>
</main>

<style>
  .stats-page {
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
    margin: 0 0 0.35rem 0;
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    color: var(--color-text);
  }

  .subtitle {
    margin: 0;
    color: var(--color-text-secondary);
    font-size: var(--font-size-base);
  }

  .tab-bar {
    display: flex;
    gap: 0;
    border-bottom: 1px solid var(--color-border);
    margin-bottom: 1.5rem;
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

  .tab-active {
    color: var(--color-text);
    border-bottom-color: var(--color-gold);
  }

  .tab-active:hover {
    color: var(--color-text);
  }

  .tab-panel {
    display: block;
  }

  .tab-hidden {
    display: none;
  }

  @media (max-width: 640px) {
    .stats-page {
      padding: 1rem;
    }

    .tab-btn {
      padding: 0.5rem 0.75rem;
      font-size: var(--font-size-sm);
    }
  }
</style>
