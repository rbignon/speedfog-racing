/**
 * speedrun.fog (the speedrun.com parody tab of /stats): URL state, time
 * formatting and record history helpers. Pure, unit-tested.
 */
import type { SpeedrunCategory, SpeedrunRun, SpeedrunRunType } from "$lib/api";

export const RUN_TYPES: SpeedrunRunType[] = ["race", "daily", "event"];

export type SpeedrunSub = "any" | "deathless";

export type SpeedrunView = "board" | "history-chart" | "history-list";

const HISTORY_VIEWS: SpeedrunView[] = ["history-chart", "history-list"];

export interface SpeedrunParams {
  pool: string | null;
  sub: SpeedrunSub;
  types: SpeedrunRunType[];
  obsolete: boolean;
  /** speedrun.com's own `view` values. */
  view: SpeedrunView;
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
    view: HISTORY_VIEWS.find((v) => v === search.get("view")) ?? "board",
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
  set("view", p.view === "board" ? null : p.view);
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
  unit: "h" | "m" | "s" | "ms";
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

const MINUTE_MS = 60_000;
const DAY_MS = 86_400_000;

function plural(n: number, unit: string): string {
  return `${n} ${unit}${n === 1 ? "" : "s"}`;
}

/** speedrun.com style relative date: `5 days ago`, `1 month ago`. */
export function speedrunAgo(dateString: string, nowMs: number): string {
  const elapsed = nowMs - new Date(dateString).getTime();
  const minutes = Math.floor(elapsed / MINUTE_MS);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${plural(minutes, "minute")} ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${plural(hours, "hour")} ago`;
  const days = Math.floor(elapsed / DAY_MS);
  if (days < 30) return `${plural(days, "day")} ago`;
  if (days < 365) return `${plural(Math.floor(days / 30), "month")} ago`;
  return `${plural(Math.floor(days / 365), "year")} ago`;
}

/** A record gain: speedrun.com minutes (`0m 16s`), or milliseconds when
 * it is under a second (`380ms`), which the minutes form would show as 0. */
export function speedrunGainParts(ms: number): SpeedrunTimePart[] {
  return ms < 1000
    ? [{ value: String(ms), unit: "ms" }]
    : speedrunTimeParts(ms);
}

/** speedrun.com's history dates: YYYY-MM-DD, the viewer's calendar day. */
export function speedrunDay(dateString: string): string {
  return new Date(dateString).toLocaleDateString("en-CA");
}

/** The viewer's calendar day as a day count, the same day `speedrunDay`
 * prints, so gaps between two shown dates add up. */
function calendarDay(dateString: string): number {
  const d = new Date(dateString);
  return Math.round(
    Date.UTC(d.getFullYear(), d.getMonth(), d.getDate()) / DAY_MS,
  );
}

/** The gap between two records, as the history list words it. */
export function speedrunDaysLater(days: number): string {
  return days === 0 ? "same day" : `${plural(days, "day")} later`;
}

export interface SpeedrunTimelineEntry {
  run: SpeedrunRun;
  /** `new`: a new record holder; `improved`: the holder beat their own record. */
  kind: "new" | "improved";
  /** Calendar days since the previous record; null for the first one. */
  daysLater: number | null;
  /** How much a new holder took off the previous record, in ms: the
   * difference of the two times as shown (whole seconds), or the raw gap
   * when both show the same second. */
  improvedBy: number | null;
}

/** speedrun.com's history list, built from the successive records (oldest
 * first). */
export function historyTimeline(
  records: SpeedrunRun[],
): SpeedrunTimelineEntry[] {
  return records.map((run, i) => {
    const previous = i > 0 ? records[i - 1] : null;
    if (previous === null) {
      return { run, kind: "new", daysLater: null, improvedBy: null };
    }
    const daysLater =
      calendarDay(run.finished_at) - calendarDay(previous.finished_at);
    const shownGain =
      Math.floor(previous.igt_ms / 1000) - Math.floor(run.igt_ms / 1000);
    return previous.user.id === run.user.id
      ? { run, kind: "improved", daysLater, improvedBy: null }
      : {
          run,
          kind: "new",
          daysLater,
          improvedBy:
            shownGain > 0 ? shownGain * 1000 : previous.igt_ms - run.igt_ms,
        };
  });
}
