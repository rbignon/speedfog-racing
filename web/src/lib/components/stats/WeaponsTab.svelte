<script lang="ts">
  import { fetchWeaponStats, type WeaponComboStat } from "$lib/api";
  import {
    loadCatalogue,
    getWeaponName,
  } from "$lib/stores/weaponsCatalogue.svelte";
  import { formatCombo } from "$lib/weapons";
  import { formatIgt } from "$lib/utils/training";

  let combos = $state<WeaponComboStat[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);

  type SortKey = "name" | "player_count" | "race_count" | "total_ticks";
  let sortKey = $state<SortKey>("total_ticks");
  let sortAsc = $state(false);

  let rows = $derived.by(() => {
    const list = combos.slice();
    list.sort((a, b) => {
      let cmp = 0;
      if (sortKey === "name") {
        cmp = formatCombo(a.ids, getWeaponName).localeCompare(
          formatCombo(b.ids, getWeaponName),
        );
      } else {
        cmp = a[sortKey] - b[sortKey];
      }
      return sortAsc ? cmp : -cmp;
    });
    return list;
  });

  $effect(() => {
    refresh();
  });

  async function refresh() {
    loading = true;
    error = null;
    try {
      await loadCatalogue();
      const data = await fetchWeaponStats();
      combos = data.combos;
    } catch (e) {
      error = e instanceof Error ? e.message : "Failed to load weapon stats.";
    } finally {
      loading = false;
    }
  }

  function handleSort(key: SortKey) {
    if (sortKey === key) {
      sortAsc = !sortAsc;
    } else {
      sortKey = key;
      sortAsc = key === "name";
    }
  }

  function sortIndicator(key: SortKey): string {
    if (sortKey !== key) return "";
    return sortAsc ? " ▲" : " ▼";
  }
</script>

{#if loading}
  <p class="loading-text">Loading weapon stats...</p>
{:else if error}
  <p class="error-text">{error}</p>
{:else}
  <div class="weapons-panel">
    <table class="weapons-table">
      <thead>
        <tr>
          <th>
            <button class="sort-btn" onclick={() => handleSort("name")}>
              Weapon{sortIndicator("name")}
            </button>
          </th>
          <th class="th-num">
            <button class="sort-btn" onclick={() => handleSort("player_count")}>
              Players{sortIndicator("player_count")}
            </button>
          </th>
          <th class="th-num">
            <button class="sort-btn" onclick={() => handleSort("race_count")}>
              Races{sortIndicator("race_count")}
            </button>
          </th>
          <th class="th-num">
            <button class="sort-btn" onclick={() => handleSort("total_ticks")}>
              Time{sortIndicator("total_ticks")}
            </button>
          </th>
          <th>Top player</th>
        </tr>
      </thead>
      <tbody>
        {#each rows as combo}
          <tr>
            <td class="weapon-name">{formatCombo(combo.ids, getWeaponName)}</td>
            <td class="num">{combo.player_count}</td>
            <td class="num">{combo.race_count}</td>
            <td class="num">{formatIgt(combo.total_ticks * 1000)}</td>
            <td>
              {#if combo.top_player_username}
                <div class="top-player-info">
                  {#if combo.top_player_avatar_url}
                    <img
                      src={combo.top_player_avatar_url}
                      alt=""
                      class="top-player-avatar"
                    />
                  {:else}
                    <div class="top-player-avatar-placeholder"></div>
                  {/if}
                  <a
                    href="/user/{combo.top_player_username}"
                    class="top-player-name"
                  >
                    {combo.top_player_display_name ?? combo.top_player_username}
                  </a>
                </div>
              {/if}
            </td>
          </tr>
        {/each}
        {#if rows.length === 0}
          <tr>
            <td colspan="5" class="empty-row">No weapon data yet.</td>
          </tr>
        {/if}
      </tbody>
    </table>
  </div>
{/if}

<style>
  .loading-text,
  .error-text {
    color: var(--color-text-disabled);
    font-style: italic;
    padding: 2rem 0;
  }

  .error-text {
    color: var(--color-danger);
  }

  .weapons-panel {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-lg);
    overflow-x: auto;
  }

  .weapons-table {
    width: 100%;
    border-collapse: collapse;
  }

  .weapons-table thead th {
    text-align: left;
    padding: 0.65rem 0.75rem;
    color: var(--color-text-secondary);
    font-weight: 500;
    font-size: var(--font-size-sm);
    text-transform: uppercase;
    letter-spacing: 0.04em;
    border-bottom: 1px solid var(--color-border);
  }

  .th-num {
    text-align: right !important;
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

  .th-num .sort-btn {
    text-align: right;
    width: 100%;
    display: block;
  }

  .weapons-table tbody td {
    padding: 0.6rem 0.75rem;
    border-top: 1px solid var(--color-border);
  }

  .weapons-table tbody tr:first-child td {
    border-top: none;
  }

  .weapon-name {
    font-weight: 500;
  }

  .num {
    text-align: right;
    font-variant-numeric: tabular-nums;
  }

  .top-player-info {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    overflow: hidden;
  }

  .top-player-avatar {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    object-fit: cover;
    flex-shrink: 0;
  }

  .top-player-avatar-placeholder {
    width: 22px;
    height: 22px;
    border-radius: 50%;
    background: var(--color-surface-elevated);
    flex-shrink: 0;
  }

  .top-player-name {
    color: var(--color-text);
    text-decoration: none;
    font-weight: 500;
    font-size: var(--font-size-sm);
    transition: color var(--transition);
    overflow: hidden;
    text-overflow: ellipsis;
    white-space: nowrap;
  }

  .top-player-name:hover {
    color: var(--color-purple);
  }

  .empty-row {
    text-align: center;
    color: var(--color-text-disabled);
    font-style: italic;
    padding: 2rem 0.75rem !important;
  }
</style>
