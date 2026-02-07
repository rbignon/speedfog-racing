/**
 * Site configuration store (Svelte 5 runes).
 */

import { fetchSiteConfig } from "$lib/api";

class SiteStore {
  comingSoon = $state(false);
  initialized = $state(false);

  async init(): Promise<void> {
    try {
      const config = await fetchSiteConfig();
      this.comingSoon = config.coming_soon;
    } catch {
      // Default to false if fetch fails
    }
    this.initialized = true;
  }
}

export const site = new SiteStore();
