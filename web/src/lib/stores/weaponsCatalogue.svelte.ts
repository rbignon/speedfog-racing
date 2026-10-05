/**
 * Frontend cache of the static weapon catalogue served by ``GET /api/weapons``.
 *
 * Loaded lazily on first access. The base name is resolved by stripping the
 * low four digits of the runtime id (affinity index times 100, up to Occult
 * 1200, plus the upgrade level). Unknown ids fall back to ``Weapon #<base>`` so a
 * future DLC the server has not yet been refreshed for still renders something
 * useful.
 */

import { normalizeId } from "$lib/weapons";

interface CatalogueEntry {
  name: string;
  wep_type: number;
}

let cache: Record<string, CatalogueEntry> | null = null;
let loading: Promise<void> | null = null;

export async function loadCatalogue(): Promise<void> {
  if (cache) return;
  if (loading) return loading;
  loading = (async () => {
    const response = await fetch("/api/weapons");
    // A failed fetch leaves the catalogue not ready: printing "Weapon #..."
    // on a broadcast is worse than a blank line, and a later call retries
    // (an OBS scene stays up for hours, so always-on consumers poll).
    if (!response.ok) {
      return;
    }
    cache = (await response.json()) as Record<string, CatalogueEntry>;
  })();
  try {
    await loading;
  } finally {
    loading = null;
  }
}

export function getWeaponName(rawId: number): string {
  const base = normalizeId(rawId);
  const entry = cache?.[String(base)];
  return entry ? entry.name : `Weapon #${base}`;
}

export function isCatalogueReady(): boolean {
  return cache !== null;
}
