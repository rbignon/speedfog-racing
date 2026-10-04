/**
 * The events on the bill (Svelte 5 runes): what the home page band, the
 * dashboard and the navbar's Event link show.
 *
 * Loaded by the layout whenever the signed-in state changes (the summary
 * carries the viewer's own signup) and refreshed by the pages that feature
 * the event, so a race that went live since the last visit shows up.
 */

import { fetchEvents, getStoredToken, type EventSummary } from "$lib/api";

class FeaturedEventStore {
  events = $state<EventSummary[]>([]);
  private requests = 0;
  /** The request in flight and the token it was sent with. */
  private inFlight: { token: string | null; done: Promise<void> } | null = null;

  /** The event to feature: the server lists the one that needs eyes first. */
  get current(): EventSummary | null {
    return this.events[0] ?? null;
  }

  /**
   * Fetch the list again. A call made while a request with the same token is
   * in flight joins it: the layout and the page that features the event both
   * refresh on the same page load. A response overtaken by a later request is
   * dropped: the layout refreshes as soon as a login lands, and the anonymous
   * answer must not arrive last and undo the viewer's signup.
   */
  refresh(): Promise<void> {
    const token = getStoredToken();
    if (this.inFlight?.token === token) return this.inFlight.done;
    // load() awaits before its finally runs, so the entry is set by then.
    const done = this.load(++this.requests);
    this.inFlight = { token, done };
    return done;
  }

  private async load(request: number): Promise<void> {
    try {
      const events = await fetchEvents();
      if (request === this.requests) this.events = events;
    } catch {
      // Keep the last list: the band is a feature, not a page the viewer asked for.
    } finally {
      if (request === this.requests) this.inFlight = null;
    }
  }
}

export const featuredEvent = new FeaturedEventStore();
