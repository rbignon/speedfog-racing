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

export function topCombos(
  combos: WeaponCombo[],
  n: number,
  minPercent: number = 0,
): TopCombo[] {
  if (combos.length === 0) return [];
  const totalAll = combos.reduce((s, c) => s + c.ticks, 0);
  if (totalAll === 0) return [];

  const sorted = combos.slice().sort((a, b) => b.ticks - a.ticks);
  const kept = sorted
    .filter((c) => (c.ticks / totalAll) * 100 >= minPercent)
    .slice(0, n);
  if (kept.length === 0) return [];

  const sumKept = kept.reduce((s, c) => s + c.ticks, 0);
  const raw = kept.map((c) => ({ entry: c, raw: (c.ticks / sumKept) * 100 }));
  const floors = raw.map((r) => Math.floor(r.raw));
  let remainder = 100 - floors.reduce((s, v) => s + v, 0);
  const order = raw
    .map((r, i) => ({ i, frac: r.raw - Math.floor(r.raw) }))
    .sort((a, b) => b.frac - a.frac);
  for (const { i } of order) {
    if (remainder <= 0) break;
    floors[i] += 1;
    remainder -= 1;
  }
  return kept.map((entry, i) => ({
    ids: entry.ids,
    ticks: entry.ticks,
    percent: floors[i],
  }));
}

export function formatCombo(
  ids: number[],
  getName: (id: number) => string,
): string {
  return ids.map(getName).join(" + ");
}
