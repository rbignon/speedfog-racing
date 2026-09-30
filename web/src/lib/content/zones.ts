import { CONTENT_ITEMS } from "./items";
import type { ContentItem, ContentKind } from "./types";

/**
 * A cluster can be composed of several fine-grained zones (e.g. a
 * cluster's `zones` list); content is keyed on those zone ids rather than
 * the cluster id itself, since the same physical place can be reached by
 * multiple cluster variants with different zone compositions (see
 * docs/STATS.md's zone codex sections for the backend side of this). An
 * item matches when any of its own zones belongs to the cluster.
 */
function itemsForZones(
  kind: ContentKind,
  zones: readonly string[],
  catalog: ContentItem[],
): ContentItem[] {
  return catalog.filter(
    (i) =>
      i.kind === kind && (i.zoneIds ?? []).some((id) => zones.includes(id)),
  );
}

export function skipsForZones(
  zones: readonly string[],
  catalog: ContentItem[] = CONTENT_ITEMS,
): ContentItem[] {
  return itemsForZones("skip", zones, catalog);
}

export function zoneTipsForZones(
  zones: readonly string[],
  catalog: ContentItem[] = CONTENT_ITEMS,
): ContentItem[] {
  return itemsForZones("tip", zones, catalog);
}

export function gameChangesForZones(
  zones: readonly string[],
  catalog: ContentItem[] = CONTENT_ITEMS,
): ContentItem[] {
  return itemsForZones("game_change", zones, catalog);
}

export function skipCountForZones(
  zones: readonly string[],
  catalog: ContentItem[] = CONTENT_ITEMS,
): number {
  return skipsForZones(zones, catalog).length;
}
