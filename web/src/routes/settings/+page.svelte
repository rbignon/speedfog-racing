<script lang="ts">
  import { onMount } from "svelte";
  import { goto } from "$app/navigation";
  import { auth } from "$lib/stores/auth.svelte";
  import {
    fetchLocales,
    fetchMyInventory,
    patchEquipped,
    updateLocale,
    updateOverlaySettings,
    type LocaleInfo,
    type MyInventoryDto,
  } from "$lib/api";
  import { rewards } from "$lib/stores/rewards.svelte";
  import RewardsPicker from "$lib/components/RewardsPicker.svelte";

  type Tab = "overlay" | "rewards";

  let activeTab = $state<Tab>("overlay");
  let locales = $state<LocaleInfo[]>([]);
  let selectedLocale = $state("en");
  let fontSize = $state(18);
  let inventory = $state<MyInventoryDto | null>(null);
  let selectedTemplateId = $state("default");
  let selectedBadgeId = $state<string | null>(null);
  let selectedSkinId = $state<string | null>(null);

  let savingOverlay = $state(false);
  let overlayError = $state<string | null>(null);
  let overlaySuccess = $state(false);

  let savingRewards = $state(false);
  let rewardsError = $state<string | null>(null);
  let rewardsSuccess = $state(false);

  onMount(async () => {
    if (!auth.isLoggedIn) {
      goto("/");
      return;
    }
    if (typeof window !== "undefined" && window.location.hash === "#rewards") {
      activeTab = "rewards";
    }
    selectedLocale = auth.user?.locale ?? "en";
    fontSize = auth.user?.overlay_settings?.font_size ?? 18;
    const [loadedLocales, loadedInventory] = await Promise.all([
      fetchLocales(),
      fetchMyInventory(),
      rewards.ensureLoaded().catch(() => undefined),
    ]);
    locales = loadedLocales;
    inventory = loadedInventory;
    if (loadedInventory) {
      selectedTemplateId =
        loadedInventory.equipped_name_template_id ?? "default";
      selectedBadgeId = loadedInventory.equipped_badge_id;
      selectedSkinId = loadedInventory.equipped_phantom_skin_id;
    }
  });

  async function saveOverlay() {
    savingOverlay = true;
    overlayError = null;
    overlaySuccess = false;
    try {
      await Promise.all([
        updateLocale(selectedLocale).then((r) => {
          if (auth.user) auth.user.locale = r.locale;
        }),
        updateOverlaySettings({ font_size: fontSize }).then((r) => {
          if (auth.user) auth.user.overlay_settings = r.overlay_settings;
        }),
      ]);
      overlaySuccess = true;
      setTimeout(() => (overlaySuccess = false), 3000);
    } catch (e) {
      overlayError = e instanceof Error ? e.message : "Failed to save";
    } finally {
      savingOverlay = false;
    }
  }

  async function saveRewards() {
    if (!inventory) return;
    savingRewards = true;
    rewardsError = null;
    rewardsSuccess = false;
    try {
      const result = await patchEquipped({
        equipped_name_template_id: selectedTemplateId,
        equipped_badge_id: selectedBadgeId,
        equipped_phantom_skin_id: selectedSkinId,
      });
      if (result && inventory) {
        inventory.equipped_name_template_id = result.equipped_name_template_id;
        inventory.equipped_badge_id = result.equipped_badge_id;
        inventory.equipped_phantom_skin_id = result.equipped_phantom_skin_id;
        if (auth.user) {
          auth.user.equipped_name_template_id =
            result.equipped_name_template_id;
          auth.user.equipped_badge_id = result.equipped_badge_id;
          auth.user.equipped_phantom_skin_id = result.equipped_phantom_skin_id;
        }
      }
      rewardsSuccess = true;
      setTimeout(() => (rewardsSuccess = false), 3000);
    } catch (e) {
      rewardsError = e instanceof Error ? e.message : "Failed to save";
    } finally {
      savingRewards = false;
    }
  }
</script>

<svelte:head>
  <title>Settings – SpeedFog Racing</title>
</svelte:head>

<main class="settings">
  <h1>Settings</h1>

  <div class="tabs">
    <button
      class="tab"
      class:active={activeTab === "overlay"}
      onclick={() => (activeTab = "overlay")}
    >
      Overlay
    </button>
    <button
      class="tab"
      class:active={activeTab === "rewards"}
      onclick={() => (activeTab = "rewards")}
    >
      Rewards
    </button>
  </div>

  {#if activeTab === "overlay"}
    <section class="setting-group">
      <p class="description">
        Customize the in-game overlay that displays race information. It
        automatically applies when you download seeds
      </p>

      <div class="setting-field">
        <label class="field-label" for="font-size">Font size</label>
        <p class="field-description">
          Size of the text displayed on the overlay.
        </p>
        <div class="setting-row">
          <div class="input-with-unit">
            <input
              id="font-size"
              type="number"
              min="8"
              max="72"
              step="1"
              bind:value={fontSize}
            />
            <span class="unit">px</span>
          </div>
          <span class="hint">8–72 px (default: 18)</span>
        </div>
      </div>

      <div class="setting-field">
        <span class="field-label">Language</span>
        <p class="field-description">
          Zone names and fog gate descriptions displayed in-game.
        </p>
        <div class="locale-select">
          {#each locales as locale}
            <label>
              <input
                type="radio"
                name="locale"
                value={locale.code}
                checked={selectedLocale === locale.code}
                onchange={() => (selectedLocale = locale.code)}
              />
              {locale.name}
            </label>
          {/each}
        </div>
      </div>
    </section>

    <div class="actions">
      <button
        class="btn btn-primary"
        onclick={saveOverlay}
        disabled={savingOverlay}
      >
        {savingOverlay ? "Saving..." : "Save"}
      </button>
      {#if overlaySuccess}
        <span class="success-msg">Saved!</span>
      {/if}
      {#if overlayError}
        <span class="error-msg">{overlayError}</span>
      {/if}
    </div>
  {:else if activeTab === "rewards"}
    <section class="setting-group" id="rewards">
      <p class="description">
        Pick a badge and a name template among the rewards you have unlocked.
      </p>

      {#if inventory && auth.user}
        <RewardsPicker
          {inventory}
          user={auth.user}
          bind:selectedTemplateId
          bind:selectedBadgeId
          bind:selectedSkinId
        />
      {:else}
        <p class="hint">Loading…</p>
      {/if}
    </section>

    <div class="actions">
      <button
        class="btn btn-primary"
        onclick={saveRewards}
        disabled={savingRewards || !inventory}
      >
        {savingRewards ? "Saving..." : "Save"}
      </button>
      {#if rewardsSuccess}
        <span class="success-msg">Saved!</span>
      {/if}
      {#if rewardsError}
        <span class="error-msg">{rewardsError}</span>
      {/if}
    </div>
  {/if}
</main>

<style>
  .settings {
    max-width: 600px;
    margin: 0 auto;
    padding: 2rem 1.5rem;
  }

  h1 {
    font-family: var(--font-display);
    font-size: 1.9rem;
    font-weight: 700;
    letter-spacing: 0.03em;
    text-transform: uppercase;
    margin-bottom: 1.5rem;
  }

  .tabs {
    display: flex;
    gap: 0;
    margin-bottom: 1.5rem;
    border-bottom: 1px solid var(--color-border);
  }

  .tab {
    padding: 0.6rem 1.25rem;
    background: none;
    border: none;
    border-bottom: 2px solid transparent;
    color: var(--color-text-secondary);
    font-family: var(--font-mono);
    font-size: var(--font-size-xs);
    font-weight: 500;
    text-transform: uppercase;
    letter-spacing: 0.09em;
    cursor: pointer;
    transition:
      color 0.15s,
      border-color 0.15s;
  }

  .tab:hover {
    color: var(--color-text);
  }

  .tab.active {
    color: var(--color-text);
    border-bottom-color: var(--color-gold);
  }

  .setting-group {
    background: var(--color-surface);
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    padding: 1.5rem;
    margin-bottom: 1.5rem;
  }

  .description {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
    margin-top: 0;
    margin-bottom: 1rem;
  }

  .locale-select {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
  }

  .locale-select label {
    display: flex;
    align-items: center;
    gap: 0.5rem;
    cursor: pointer;
    font-size: var(--font-size-base);
  }

  .setting-field {
    margin-top: 1.25rem;
    padding-top: 1.25rem;
    border-top: 1px solid var(--color-border);
  }

  .field-label {
    font-size: var(--font-size-base);
    font-weight: 500;
    display: block;
    margin-bottom: 0.25rem;
  }

  .field-description {
    color: var(--color-text-secondary);
    font-size: var(--font-size-xs);
    margin-bottom: 0.75rem;
  }

  .setting-row {
    display: flex;
    align-items: center;
    gap: 0.75rem;
  }

  .input-with-unit {
    display: flex;
    align-items: center;
    gap: 0.25rem;
  }

  .input-with-unit input {
    width: 5rem;
    padding: 0.375rem 0.5rem;
    border: 1px solid var(--color-border);
    border-radius: var(--radius-sm);
    background: var(--color-bg);
    color: var(--color-text);
    font-size: var(--font-size-base);
  }

  .unit {
    color: var(--color-text-secondary);
    font-size: var(--font-size-sm);
  }

  .hint {
    color: var(--color-text-disabled);
    font-size: var(--font-size-xs);
  }

  .actions {
    display: flex;
    align-items: center;
    gap: 1rem;
    justify-content: end;
  }

  .success-msg {
    color: var(--color-green);
    font-size: var(--font-size-sm);
  }

  .error-msg {
    color: var(--color-danger);
    font-size: var(--font-size-sm);
  }
</style>
