import { CONTENT_ITEMS } from "./items";
import type { ContentItem } from "./types";

/**
 * A cluster can be composed of several fine-grained zones (e.g. a
 * cluster's `zones` list); content is keyed on those zone ids rather than
 * the cluster id itself, since the same physical place can be reached by
 * multiple cluster variants with different zone compositions (see
 * docs/STATS.md's zone codex sections for the backend side of this).
 */
export function skipsForZones(
  zones: readonly string[],
  catalog: ContentItem[] = CONTENT_ITEMS,
): ContentItem[] {
  return catalog.filter(
    (i) =>
      i.kind === "skip" && i.zoneId !== undefined && zones.includes(i.zoneId),
  );
}

export function zoneTipsForZones(
  zones: readonly string[],
  catalog: ContentItem[] = CONTENT_ITEMS,
): ContentItem[] {
  return catalog.filter(
    (i) =>
      i.kind === "tip" && i.zoneId !== undefined && zones.includes(i.zoneId),
  );
}

export function skipCountForZones(
  zones: readonly string[],
  catalog: ContentItem[] = CONTENT_ITEMS,
): number {
  return skipsForZones(zones, catalog).length;
}
