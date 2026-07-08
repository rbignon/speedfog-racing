import { CONTENT_ITEMS } from "./items";
import type { ContentItem } from "./types";

/**
 * Cluster ids carry a per-seed 4-hex suffix ("stormveil_c3d4"); the same
 * physical place can hash differently across seeds, so content keys on the
 * stripped prefix (the backend merges zone stats by display name for the
 * same reason).
 */
export function zoneKeyOf(nodeId: string): string {
  return nodeId.replace(/_[0-9a-f]{4}$/, "");
}

export function skipsForZone(
  nodeId: string,
  catalog: ContentItem[] = CONTENT_ITEMS,
): ContentItem[] {
  const key = zoneKeyOf(nodeId);
  return catalog.filter((i) => i.kind === "skip" && i.zoneKey === key);
}

export function zoneTipsForZone(
  nodeId: string,
  catalog: ContentItem[] = CONTENT_ITEMS,
): ContentItem[] {
  const key = zoneKeyOf(nodeId);
  return catalog.filter((i) => i.kind === "tip" && i.zoneKey === key);
}

export function skipCountForZone(
  nodeId: string,
  catalog: ContentItem[] = CONTENT_ITEMS,
): number {
  return skipsForZone(nodeId, catalog).length;
}
