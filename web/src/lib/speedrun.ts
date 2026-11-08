/**
 * The /speedrun page (speedrun.com style boards): URL state, time
 * formatting and record history helpers. Pure, unit-tested.
 */
import type {
  RunMode,
  SpeedrunCategory,
  SpeedrunRun,
  SpeedrunRunType,
} from "$lib/api";

export const RUN_TYPES: SpeedrunRunType[] = ["race", "daily", "event", "solo"];

/** Set Seed: every run but those on an excluded or too old seed, whether the
 * seed was chosen or served. Random Seed: blind runs only. */
export type SpeedrunSub = "set" | "random";

export type SpeedrunView = "board" | "history-chart" | "history-list";

const HISTORY_VIEWS: SpeedrunView[] = ["history-chart", "history-list"];

export interface SpeedrunParams {
  pool: string | null;
  sub: SpeedrunSub;
  /** Deathless only. */
  deathless: boolean;
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
    sub: search.get("sub") === "random" ? "random" : "set",
    deathless: search.get("deathless") === "1",
    types: types.length > 0 ? types : [...RUN_TYPES],
    obsolete: search.get("obsolete") === "1",
    view: HISTORY_VIEWS.find((v) => v === search.get("view")) ?? "board",
  };
}

/** Writes the non-default values into `url`, removes the default ones and
 * leaves every other key alone. */
export function writeSpeedrunParams(url: URL, p: SpeedrunParams): void {
  const set = (key: string, value: string | null) => {
    if (value === null) url.searchParams.delete(key);
    else url.searchParams.set(key, value);
  };
  set("pool", p.pool);
  set("sub", p.sub === "random" ? "random" : null);
  set("deathless", p.deathless ? "1" : null);
  set(
    "types",
    p.types.length < RUN_TYPES.length
      ? canonicalTypes(p.types).join(",")
      : null,
  );
  set("obsolete", p.obsolete ? "1" : null);
  set("view", p.view === "board" ? null : p.view);
}

/** The pool to show: the asked one when it exists, the first otherwise. */
export function resolvePool(
  p: SpeedrunParams,
  categories: SpeedrunCategory[],
): string | null {
  if (categories.length === 0) return null;
  return (categories.find((c) => c.pool === p.pool) ?? categories[0]).pool;
}

/** Toggles one run type; the last selected type cannot be removed. */
/** Clicking a recent run opens its category's Set Seed board, where its
 * place was computed: every run type, no deathless filter. */
export function recentRunParams(
  current: SpeedrunParams,
  pool: string,
): SpeedrunParams {
  return {
    ...current,
    pool,
    sub: "set",
    deathless: false,
    types: [...RUN_TYPES],
  };
}

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

/** A run's own page: a Daily Seed run's day, a race run's race, a solo run's
 * session. */
export function speedrunRunHref(run: {
  race_id: string | null;
  daily_date: string | null;
  session_id: string | null;
}): string {
  if (run.daily_date) return `/daily/${run.daily_date}`;
  if (run.race_id) return `/race/${run.race_id}`;
  return `/training/${run.session_id}`;
}

/** A seed's page (`/speedrun/seed/<n>`), focused on one of its runs when
 * `runId` is given (`?run=<id>` ticks it on arrival). */
export function seedPageHref(
  seedNumber: string,
  runId?: string | null,
): string {
  const path = `/speedrun/seed/${encodeURIComponent(seedNumber)}`;
  return runId ? `${path}?run=${encodeURIComponent(runId)}` : path;
}

/** The fewest characters of a seed ID worth looking up: the 6 the boards
 * show, unambiguous most of the time. */
export const SEED_ID_MIN_LENGTH = 6;

/** A pool's Speedrun floor as typed in the admin panel: null when empty (the
 * server default applies), a whole number 0 or more, or undefined for
 * anything else, refused before any request. */
export function parseSpeedrunFloor(raw: string): number | null | undefined {
  const text = raw.trim();
  if (text === "") return null;
  return /^\d+$/.test(text) ? Number(text) : undefined;
}

/** Race creation for a speedrun race: the Speedrun option on, `pool` picked. */
export function speedrunRaceNewHref(pool: string): string {
  return `/race/new?mode=speedrun&pool=${encodeURIComponent(pool)}`;
}

/** Race creation for a Set Seed race on `seed`. */
export function setSeedRaceNewHref(seed: string): string {
  return `/race/new?seed=${encodeURIComponent(seed)}`;
}

/** What `/race/new` was opened for: a Set Seed race on `seed`, else a
 * speedrun race when `mode=speedrun`, and the pool to preselect. */
export interface RaceNewParams {
  seed: string | null;
  speedrun: boolean;
  pool: string | null;
}

export function parseRaceNewParams(search: URLSearchParams): RaceNewParams {
  const seed = search.get("seed")?.trim() || null;
  return {
    seed,
    speedrun: seed === null && search.get("mode") === "speedrun",
    pool: search.get("pool")?.trim() || null,
  };
}

/** The Start a run window open in Set Seed mode on `seed`, over the board
 * of `category` (a seed's category key; null for the default board). */
export function startRunHref(category: string | null, seed: string): string {
  const pool = category === null ? "" : `pool=${encodeURIComponent(category)}&`;
  return `/speedrun?${pool}start=set&seed=${encodeURIComponent(seed)}`;
}

/** The Start a run window open in Random Seed mode over the board of
 * `category`, the one it draws from. */
export function startRandomRunHref(category: string): string {
  return `/speedrun?pool=${encodeURIComponent(category)}&start=random`;
}

/** What a `/speedrun` URL opens the Start a run window on: Random Seed
 * (`start=random`) or Set Seed with `seed` typed in (`start=set&seed=<n>`,
 * "" for an empty field). */
export type StartRun = { sub: "random" } | { sub: "set"; seed: string };

/** Null for no window. */
export function parseStartRun(search: URLSearchParams): StartRun | null {
  switch (search.get("start")) {
    case "random":
      return { sub: "random" };
    case "set":
      return { sub: "set", seed: search.get("seed")?.trim() ?? "" };
    default:
      return null;
  }
}

/** Where a run's seed links to: its seed page, focused on the run. */
export function speedrunSeedHref(run: SpeedrunRun): string {
  return seedPageHref(run.seed_number, run.run_id);
}

/** A race's seed page, once a link to it is worth showing: the race is
 * finished, or it is a Set Seed race (a replay: its seed is already public).
 * The server's public rule stays the guard; this only spares a link to a page
 * that would still be hidden. */
export function raceSeedPageHref(race: {
  seed_number: string | null;
  status: string;
  mode: RunMode;
}): string | null {
  if (!race.seed_number) return null;
  return race.status === "finished" || race.mode === "set_seed"
    ? seedPageHref(race.seed_number)
    : null;
}

/** A solo session's seed page: a Set Seed session's, or a Speedrun
 * session's once it is no longer active. A normal (practice) session plays a
 * training seed, which has no page. */
export function sessionSeedPageHref(session: {
  seed_number: string | null;
  status: string;
  mode: RunMode;
}): string | null {
  if (!session.seed_number || session.mode === "normal") return null;
  if (session.mode === "speedrun" && session.status === "active") return null;
  return seedPageHref(session.seed_number);
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

/** The OBS overlay of a board (`/overlay/speedrun/<pool>`): the board's own
 * `sub`, `deathless` and `types`, plus the rows to show and the player to pin. */
export interface SpeedrunOverlayParams {
  sub: SpeedrunSub;
  deathless: boolean;
  types: SpeedrunRunType[];
  /** Rows always shown, from the first place. */
  top: number;
  /** Rows paging through the players after the top. */
  cycle: number;
  /** The last rank the cycling rows reach. */
  until: number;
  /** Twitch username whose row stays pinned; null for none. */
  player: string | null;
}

export const SPEEDRUN_OVERLAY_DEFAULTS = { top: 3, cycle: 3, until: 20 };

function rowCount(raw: string | null, fallback: number): number {
  if (raw === null || !/^\d+$/.test(raw)) return fallback;
  return parseInt(raw, 10);
}

export function parseSpeedrunOverlayParams(
  search: URLSearchParams,
): SpeedrunOverlayParams {
  const { sub, deathless, types } = parseSpeedrunParams(search);
  return {
    sub,
    deathless,
    types,
    top: rowCount(search.get("top"), SPEEDRUN_OVERLAY_DEFAULTS.top),
    cycle: rowCount(search.get("cycle"), SPEEDRUN_OVERLAY_DEFAULTS.cycle),
    until: rowCount(search.get("until"), SPEEDRUN_OVERLAY_DEFAULTS.until),
    player: search.get("player")?.trim() || null,
  };
}

/** The overlay's URL, default values left out. */
export function speedrunOverlayUrl(
  origin: string,
  pool: string,
  p: SpeedrunOverlayParams,
): string {
  const url = new URL(`/overlay/speedrun/${encodeURIComponent(pool)}`, origin);
  writeSpeedrunParams(url, {
    pool: null,
    sub: p.sub,
    deathless: p.deathless,
    types: p.types,
    obsolete: false,
    view: "board",
  });
  for (const key of ["top", "cycle", "until"] as const) {
    if (p[key] !== SPEEDRUN_OVERLAY_DEFAULTS[key]) {
      url.searchParams.set(key, String(p[key]));
    }
  }
  if (p.player) url.searchParams.set("player", p.player);
  return url.toString();
}

export interface SpeedrunOverlayRows {
  top: SpeedrunRun[];
  /** The cycling rows, `cycle` per page (the last one may be shorter). */
  pages: SpeedrunRun[][];
  /** The pinned row: the player's, unless it already shows in the top. */
  self: SpeedrunRun | null;
  /** The player's user id, to highlight their row wherever it shows. */
  selfId: string | null;
}

/** Splits a ranked board (best runs only) into the overlay's rows: the top,
 * the pages cycling through the next players up to rank `until`, and the
 * player's pinned row, which never also shows in the cycle. */
export function speedrunOverlayRows(
  runs: SpeedrunRun[],
  o: Pick<SpeedrunOverlayParams, "top" | "cycle" | "until" | "player">,
): SpeedrunOverlayRows {
  const player = o.player?.toLowerCase() ?? null;
  const index =
    player === null
      ? -1
      : runs.findIndex((r) => r.user.twitch_username.toLowerCase() === player);
  const self = index >= o.top ? runs[index] : null;
  const pool = runs
    .slice(o.top)
    .filter((r) => r !== self && r.rank !== null && r.rank <= o.until);
  const pages: SpeedrunRun[][] = [];
  if (o.cycle > 0) {
    for (let i = 0; i < pool.length; i += o.cycle) {
      pages.push(pool.slice(i, i + o.cycle));
    }
  }
  return {
    top: runs.slice(0, o.top),
    pages,
    self,
    selfId: index >= 0 ? runs[index].user.id : null,
  };
}
