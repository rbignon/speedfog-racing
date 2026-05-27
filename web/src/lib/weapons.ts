import type { WeaponCombo, ZoneHistoryEntry } from "$lib/zone-history";

export interface TopCombo extends WeaponCombo {
  percent: number;
}

function sumCombos(combos: WeaponCombo[]): WeaponCombo[] {
  const byKey = new Map<string, WeaponCombo>();
  for (const entry of combos) {
    const key = entry.ids.join("_");
    const existing = byKey.get(key);
    if (existing) {
      existing.ticks += entry.ticks;
    } else {
      byKey.set(key, { ids: [...entry.ids], ticks: entry.ticks });
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

export function topCombos(combos: WeaponCombo[], n: number): TopCombo[] {
  if (combos.length === 0) return [];
  const total = combos.reduce((s, c) => s + c.ticks, 0);
  if (total === 0) return [];
  return combos
    .slice()
    .sort((a, b) => b.ticks - a.ticks)
    .slice(0, n)
    .map((c) => ({ ...c, percent: Math.round((c.ticks / total) * 100) }));
}

export function formatCombo(
  ids: number[],
  getName: (id: number) => string,
): string {
  return ids.map(getName).join(" + ");
}
