/**
 * speedrun.fog (the speedrun.com parody tab of /stats): URL state, time
 * formatting and record history helpers. Pure, unit-tested.
 */
import type { SpeedrunCategory, SpeedrunRunType } from "$lib/api";

export const RUN_TYPES: SpeedrunRunType[] = ["race", "daily", "event"];

export type SpeedrunSub = "any" | "deathless";

export interface SpeedrunParams {
  pool: string | null;
  sub: SpeedrunSub;
  types: SpeedrunRunType[];
  obsolete: boolean;
  view: "board" | "history";
}

/** Run types in canonical order; unknown values dropped. */
function canonicalTypes(values: Iterable<string>): SpeedrunRunType[] {
  const wanted = new Set(values);
  return RUN_TYPES.filter((t) => wanted.has(t));
}

export function parseSpeedrunParams(search: URLSearchParams): SpeedrunParams {
  const types = canonicalTypes((search.get("types") ?? "").split(","));
  return {
    pool: search.get("pool") || null,
    sub: search.get("sub") === "deathless" ? "deathless" : "any",
    types: types.length > 0 ? types : [...RUN_TYPES],
    obsolete: search.get("obsolete") === "1",
    view: search.get("view") === "history" ? "history" : "board",
  };
}

/** Writes the non-default values into `url`, removes the default ones and
 * leaves every other key (such as `tab`) alone. */
export function writeSpeedrunParams(url: URL, p: SpeedrunParams): void {
  const set = (key: string, value: string | null) => {
    if (value === null) url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  };
  set("pool", p.pool);
  set("sub", p.sub === "deathless" ? "deathless" : null);
  set(
    "types",
    p.types.length < RUN_TYPES.length
      ? canonicalTypes(p.types).join(",")
      : null,
  );
  set("obsolete", p.obsolete ? "1" : null);
  set("view", p.view === "history" ? "history" : null);
}

/** The board to show: the asked pool and subcategory when they exist, the
 * first category and the pool's first subcategory otherwise. */
export function resolveCategory(
  p: SpeedrunParams,
  categories: SpeedrunCategory[],
): { pool: string; sub: SpeedrunSub } | null {
  if (categories.length === 0) return null;
  const category = categories.find((c) => c.pool === p.pool) ?? categories[0];
  const sub = category.subcategories.includes(p.sub)
    ? p.sub
    : category.subcategories[0];
  return { pool: category.pool, sub };
}

/** Toggles one run type; the last selected type cannot be removed. */
export function toggleRunType(
  types: SpeedrunRunType[],
  t: SpeedrunRunType,
): SpeedrunRunType[] {
  if (!types.includes(t)) return canonicalTypes([...types, t]);
  if (types.length === 1) return [...types];
  return canonicalTypes(types.filter((x) => x !== t));
}

export interface SpeedrunTimePart {
  value: string;
  unit: "h" | "m" | "s";
}

/** speedrun.com style time: `21m 43s`, `1h 02m 30s`. */
export function speedrunTimeParts(ms: number): SpeedrunTimePart[] {
  const totalSeconds = Math.floor(ms / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor(totalSeconds / 60) % 60;
  const seconds = String(totalSeconds % 60).padStart(2, "0");
  if (hours > 0) {
    return [
      { value: String(hours), unit: "h" },
      { value: String(minutes).padStart(2, "0"), unit: "m" },
      { value: seconds, unit: "s" },
    ];
  }
  return [
    { value: String(minutes), unit: "m" },
    { value: seconds, unit: "s" },
  ];
}

/** A Daily Seed run links to its day, any other run to its race. */
export function speedrunRaceHref(run: {
  race_id: string;
  daily_date: string | null;
}): string {
  return run.daily_date ? `/daily/${run.daily_date}` : `/race/${run.race_id}`;
}

/** The record over time as a step line in data units (`[timeMs, igtMs]`):
 * each record holds until the next one, the last one until `nowMs`. */
export function historyPolyline(
  records: { finished_at: string; igt_ms: number }[],
  nowMs: number,
): [number, number][] {
  const points: [number, number][] = [];
  records.forEach((record, i) => {
    const t = new Date(record.finished_at).getTime();
    if (i > 0) points.push([t, records[i - 1].igt_ms]);
    points.push([t, record.igt_ms]);
  });
  if (records.length > 0) {
    points.push([nowMs, records[records.length - 1].igt_ms]);
  }
  return points;
}
