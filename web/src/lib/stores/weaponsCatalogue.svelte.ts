/**
 * Frontend cache of the static weapon catalogue served by ``GET /api/weapons``.
 *
 * Loaded lazily on first access. The base name is resolved by stripping the
 * low three digits of the runtime id (affinity in the hundreds, upgrade level
 * in the tens and units). Unknown ids fall back to ``Weapon #<base>`` so a
 * future DLC the server has not yet been refreshed for still renders something
 * useful.
 */

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
    if (!response.ok) {
      cache = {};
      return;
    }
    cache = (await response.json()) as Record<string, CatalogueEntry>;
  })();
  await loading;
  loading = null;
}

export function getWeaponName(rawId: number): string {
  const base = rawId - (rawId % 1000);
  const entry = cache?.[String(base)];
  return entry ? entry.name : `Weapon #${base}`;
}

export function isCatalogueReady(): boolean {
  return cache !== null;
}
