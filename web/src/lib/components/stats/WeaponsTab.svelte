<script lang="ts">
  import { onMount } from "svelte";
  import { fetchWeaponStats, type WeaponComboStat } from "$lib/api";
  import {
    loadCatalogue,
    getWeaponName,
  } from "$lib/stores/weaponsCatalogue.svelte";
  import { formatCombo } from "$lib/weapons";

  let combos = $state<WeaponComboStat[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  async function refresh() {
    loading = true;
    error = null;
    try {
      await loadCatalogue();
      const data = await fetchWeaponStats();
      combos = data.combos;
    } catch (e) {
      error = e instanceof Error ? e.message : String(e);
    } finally {
      loading = false;
    }
  }

  onMount(refresh);
</script>

<section class="weapons-tab">
  <h2>Top weapon combos</h2>
  {#if loading}
    <p class="loading-text">Loading...</p>
  {:else if error}
    <p class="error-text">Error: {error}</p>
  {:else if combos.length === 0}
    <p class="empty">No data for the current filters.</p>
  {:else}
    <ol class="list">
      {#each combos as combo}
        <li>
          <span class="combo">{formatCombo(combo.ids, getWeaponName)}</span>
          <span class="ticks">{combo.total_ticks} ticks</span>
          <span class="races">{combo.race_count} races</span>
        </li>
      {/each}
    </ol>
  {/if}
</section>

<style>
  .weapons-tab {
    padding: 1rem 0;
  }
  .list {
    list-style: none;
    padding: 0;
    margin: 0;
    display: flex;
    flex-direction: column;
    gap: 0.4rem;
  }
  .list li {
    display: grid;
    grid-template-columns: 1fr auto auto;
    gap: 1rem;
    padding: 0.5rem 0.75rem;
    background: var(--color-bg-elevated, #1f1f2e);
    border-radius: var(--radius-sm, 4px);
  }
  .ticks,
  .races {
    color: var(--color-text-secondary, #888);
    font-variant-numeric: tabular-nums;
  }
  .empty,
  .loading-text,
  .error-text {
    color: var(--color-text-secondary, #888);
  }
</style>
