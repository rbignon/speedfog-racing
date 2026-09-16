/**
 * The events on the bill (Svelte 5 runes): what the home page band, the
 * dashboard and the navbar's Event link show.
 *
 * Loaded by the layout whenever the signed-in state changes (the summary
 * carries the viewer's own signup) and refreshed by the pages that feature
 * the event, so a race that went live since the last visit shows up.
 */

import { fetchEvents, type EventSummary } from "$lib/api";

class FeaturedEventStore {
  events = $state<EventSummary[]>([]);
  private requests = 0;

  /** The event to feature: the server lists the one that needs eyes first. */
  get current(): EventSummary | null {
    return this.events[0] ?? null;
  }

  /**
   * Fetch the list again. A response overtaken by a later request is
   * dropped: the layout refreshes as soon as a login lands, and the
   * anonymous answer must not arrive last and undo the viewer's signup.
   */
  async refresh(): Promise<void> {
    const request = ++this.requests;
    try {
      const events = await fetchEvents();
      if (request === this.requests) this.events = events;
    } catch {
      // Keep the last list: the band is a feature, not a page the viewer asked for.
    }
  }
}

export const featuredEvent = new FeaturedEventStore();
