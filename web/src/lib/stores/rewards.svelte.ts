/**
 * Rewards catalog store (Svelte 5 runes).
 *
 * The catalog is a small static payload exposed at GET /api/rewards/catalog.
 * It rarely changes (only when a deploy adds/removes entries) and contains no
 * user-specific data, so we cache the first successful fetch in memory.
 */

import type { BadgeDef, NameTemplateDef, RewardsCatalog } from "$lib/api";

class RewardsStore {
  catalog = $state<RewardsCatalog | null>(null);

  private inFlight: Promise<void> | null = null;

  async ensureLoaded(): Promise<void> {
    if (this.catalog !== null) return;
    if (this.inFlight) return this.inFlight;
    this.inFlight = (async () => {
      const resp = await fetch("/api/rewards/catalog");
      if (!resp.ok) {
        throw new Error(`Failed to fetch rewards catalog: ${resp.status}`);
      }
      this.catalog = (await resp.json()) as RewardsCatalog;
    })();
    try {
      await this.inFlight;
    } finally {
      this.inFlight = null;
    }
  }

  lookupBadge(id: string | null | undefined): BadgeDef | null {
    if (!id || !this.catalog) return null;
    return this.catalog.badges.find((b) => b.id === id) ?? null;
  }

  lookupTemplate(id: string | null | undefined): NameTemplateDef | null {
    if (!this.catalog) return null;
    const target = id ?? "default";
    return this.catalog.name_templates.find((t) => t.id === target) ?? null;
  }
}

export const rewards = new RewardsStore();
