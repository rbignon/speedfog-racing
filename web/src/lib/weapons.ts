import type { WeaponCombo, ZoneHistoryEntry } from "$lib/zone-history";

export interface TopCombo extends WeaponCombo {
  percent: number;
}

// Runtime weapon ID = base row + affinity index * 100 (Standard 0 up to
// Occult 1200) + upgrade level (0..25); the base row ends with four zeros.
// Mirror of BASE_ROW_MODULUS in server/speedfog_racing/services/weapons.py.
export const BASE_ROW_MODULUS = 10_000;

export function normalizeId(id: number): number {
  return id - (id % BASE_ROW_MODULUS);
}

function sumCombos(combos: WeaponCombo[]): WeaponCombo[] {
  const byKey = new Map<string, WeaponCombo>();
  for (const entry of combos) {
    const normalized = entry.ids.map(normalizeId);
    const key = normalized.join("_");
    const existing = byKey.get(key);
    if (existing) {
      existing.ticks += entry.ticks;
    } else {
      byKey.set(key, { ids: normalized, ticks: entry.ticks });
    }
  }
  return [...byKey.values()].sort((a, b) => b.ticks - a.ticks);
}

export function aggregateAllCombos(history: ZoneHistoryEntry[]): WeaponCombo[] {
  const all: WeaponCombo[] = [];
  for (const entry of history) {
    if (entry.weapons) all.push(...entry.weapons);
  }
  return sumCombos(all);
}

export function aggregateZoneCombos(
  history: ZoneHistoryEntry[],
  nodeId: string,
): WeaponCombo[] {
  const all: WeaponCombo[] = [];
  for (const entry of history) {
    if (entry.node_id === nodeId && entry.weapons) all.push(...entry.weapons);
  }
  return sumCombos(all);
}

export function topCombos(
  combos: WeaponCombo[],
  n: number,
  minPercent: number = 0,
): TopCombo[] {
  if (combos.length === 0) return [];
  const total = combos.reduce((s, c) => s + c.ticks, 0);
  if (total === 0) return [];
  return combos
    .slice()
    .sort((a, b) => b.ticks - a.ticks)
    .filter((c) => (c.ticks / total) * 100 >= minPercent)
    .slice(0, n)
    .map((c) => ({ ...c, percent: Math.round((c.ticks / total) * 100) }));
}

export function formatCombo(
  ids: number[],
  getName: (id: number) => string,
): string {
  return ids.map(getName).join(" + ");
}

/** The highest-ticks combo of a weapons list (first wins a tie). */
function topOf(weapons: WeaponCombo[]): number[] | null {
  let best: WeaponCombo | null = null;
  for (const c of weapons) {
    if (!best || c.ticks > best.ticks) best = c;
  }
  return best ? best.ids : null;
}

/**
 * The most-used combo of the runner's latest zone with any weapon
 * observations: the best guess a zone_history snapshot alone can give for
 * what they are wielding. It seeds the live display on race_state; from
 * then on each player_update carries the actually observed hands (the
 * `weapons` field), which supersedes this. Raw runtime ids are returned
 * (affinity and upgrade preserved); display resolves names via the
 * catalogue.
 */
export function zoneTopCombo(
  history: ZoneHistoryEntry[] | null | undefined,
): number[] | null {
  if (!history) return null;
  for (let i = history.length - 1; i >= 0; i--) {
    const weapons = history[i].weapons;
    if (weapons?.length) return topOf(weapons);
  }
  return null;
}
