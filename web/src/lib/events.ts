import type {
  EventDetail,
  EventFact,
  EventPhase,
  EventStage,
  EventSummary,
  User,
} from "$lib/api";

export type EventBlock =
  | "intro"
  | "format"
  | "take_part"
  | "practice"
  | "seeds"
  | "ladder_qualified"
  | "live"
  | "champions"
  | "bracket_ladder";

/**
 * Which blocks the page shows, top to bottom, for a phase. While the event
 * can still be joined, an introduction to SpeedFog opens the page for
 * visitors who have never played it. The take-part block carries the
 * qualifier rules, the bracket block the playoff rules and the next (or
 * current) evening's races; from the cut on the bracket replaces the
 * qualified column, the ladder staying under it.
 */
export function blockOrder(phase: EventPhase): EventBlock[] {
  switch (phase) {
    case "upcoming":
    case "qualifier":
      return [
        "intro",
        "format",
        "take_part",
        "practice",
        "seeds",
        "ladder_qualified",
      ];
    case "cut":
      return ["bracket_ladder"];
    case "playoffs":
      return ["live", "bracket_ladder"];
    case "finished":
      return ["champions", "bracket_ladder"];
  }
}

type FactsInput = Pick<
  EventDetail,
  "facts" | "modes" | "seeds_per_mode" | "stages"
>;

/**
 * The format block's tiles: the config's own facts when it sets any, else
 * four derived from the event's shape (seed and mode counts, the mode labels,
 * stage and race counts, the newcomers' final day).
 */
export function eventFacts(
  detail: FactsInput,
  formatDay: (iso: string) => string,
): EventFact[] {
  if (detail.facts && detail.facts.length > 0) return detail.facts;
  const races = detail.stages[0]?.races_expected;
  const newcomers = detail.stages.find((s) => s.kind === "newcomers");
  const facts: EventFact[] = [
    {
      title: "Qualifier",
      lines: [
        `${detail.seeds_per_mode * detail.modes.length} seeds`,
        `${detail.modes.length} modes`,
      ],
    },
    { title: "Modes", lines: detail.modes.map((m) => m.label) },
    {
      title: "Playoffs",
      lines: [
        `${detail.stages.length} stages`,
        ...(races ? [`${races} races each`] : []),
      ],
    },
  ];
  if (newcomers) {
    facts.push({
      title: "Newcomers",
      lines: newcomers.date
        ? ["Own final", formatDay(newcomers.date)]
        : ["Own final"],
    });
  }
  return facts;
}

/**
 * One entry per slot, in slot order: the attached item (a qualifier seed, a
 * stage race), or null for a slot nothing is attached to yet.
 */
export function fillSlots<T extends { index: number }>(
  items: T[],
  count: number,
): (T | null)[] {
  return Array.from(
    { length: count },
    (_, i) => items.find((it) => it.index === i + 1) ?? null,
  );
}

type LiveStageInput = Pick<EventDetail, "live_race" | "stages">;

/** The stage that owns the currently live race, or null when there is none or no stage matches. */
export function liveStage(detail: LiveStageInput): EventStage | null {
  if (!detail.live_race) return null;
  return (
    detail.stages.find((s) =>
      s.races.some((r) => r.race.id === detail.live_race?.id),
    ) ?? null
  );
}

/**
 * A race name without its leading stage label ("Semi A - Race 1 - Standard"
 * shown under a "Semi A" heading reads "Race 1 - Standard"); unchanged when
 * the name does not start with the label. Both the hyphen and the older
 * middle-dot separator are recognised.
 */
export function stripStagePrefix(name: string, stageLabel: string): string {
  for (const sep of [" - ", " · "]) {
    const prefix = `${stageLabel}${sep}`;
    if (name.startsWith(prefix)) return name.slice(prefix.length);
  }
  return name;
}

/** A stage's winner: its leader once the stage is complete, else null. */
export function stageWinner(stage: EventStage): User | null {
  return stage.complete ? (stage.results[0]?.user ?? null) : null;
}

export interface Champion {
  kind: "final" | "newcomers";
  label: string;
  user: User;
  /** Position on the qualifier ladder, null if unranked there. */
  ladderRank: number | null;
  /**
   * Races of the evening the winner finished first (a race nobody finished
   * counts for no one, even though the ladder still scores its deepest run).
   */
  wins: number;
  racesExpected: number;
  /** The weapon carried the longest over the whole event, if any. */
  weapon: string | null;
}

type ChampionsInput = Pick<EventDetail, "stages" | "ladder">;

/**
 * The decided winners of the stages that crown one, the final first and
 * the newcomers' final after it, with where they came from on the ladder,
 * their evening's record and their signature weapon.
 */
export function champions(detail: ChampionsInput): Champion[] {
  const crown = (kind: Champion["kind"], label: string): Champion[] => {
    const stage = detail.stages.find((s) => s.kind === kind && s.complete);
    const user = stage ? stageWinner(stage) : null;
    if (!stage || !user) return [];
    const wins = stage.races.filter(
      (r) =>
        r.race.status === "finished" &&
        r.race.participant_previews.find((p) => p.placement === 1)?.id ===
          user.id,
    ).length;
    return [
      {
        kind,
        label,
        user,
        ladderRank:
          detail.ladder.entries.find((e) => e.user.id === user.id)?.rank ??
          null,
        wins,
        racesExpected: stage.races_expected,
        weapon: stage.results[0].signature_weapon?.name ?? null,
      },
    ];
  };
  return [...crown("final", "Champion"), ...crown("newcomers", "Newcomers")];
}

type ShownStageInput = Pick<
  EventDetail,
  "current_stage_key" | "next_stage" | "stages" | "phase"
>;

/**
 * The evening whose races the bracket block lists: the current stage during
 * the playoffs, else the next one, else the last one once everything ran;
 * none while no evening can honestly be called next.
 */
export function shownStage(detail: ShownStageInput): EventStage | null {
  const key =
    detail.current_stage_key ??
    detail.next_stage?.key ??
    (detail.phase === "finished" ? detail.stages.at(-1)?.key : undefined);
  return detail.stages.find((s) => s.key === key) ?? null;
}

/** What a stage's date line reads while its races are not scheduled yet. */
export const DATE_TO_BE_AGREED = "Date to be agreed";

type SectionInput = Pick<EventDetail, "live_race"> & ShownStageInput;

export interface RacesSection {
  signal: { cls: string; text: string };
  meta: string;
}

/**
 * The meta row under the races section title, about the stage whose races
 * the section lists: live while one of its races runs ("Race 2 of 3"),
 * finished once complete, up next (the date) until one of its races has
 * started, in progress between two of its races.
 */
export function racesSection(
  detail: SectionInput,
  formatDate: (iso: string) => string,
  now: Date,
): RacesSection | null {
  const stage = shownStage(detail);
  if (!stage) return null;
  const live = detail.live_race
    ? stage.races.find((r) => r.race.id === detail.live_race?.id)
    : undefined;
  if (live) {
    return {
      signal: { cls: "signal-running", text: "Live now" },
      meta: `Race ${live.index} of ${stage.races_expected}`,
    };
  }
  if (stage.complete) {
    return {
      signal: { cls: "signal-finished", text: "Finished" },
      meta: stage.date ? formatDate(stage.date) : DATE_TO_BE_AGREED,
    };
  }
  const started = stage.races.some((r) => r.race.status !== "setup");
  if (
    !started ||
    (stage.date !== null && new Date(stage.date).getTime() > now.getTime())
  ) {
    return {
      signal: { cls: "signal-setup", text: "Up next" },
      meta: stage.date ? formatDate(stage.date) : DATE_TO_BE_AGREED,
    };
  }
  const played = stage.races.filter((r) => r.race.status === "finished").length;
  return {
    signal: { cls: "signal-active", text: "In progress" },
    meta: `${played} of ${stage.races_expected} races played`,
  };
}

/** Time left before a seed closes, in the coarsest useful unit. */
export function timeRemaining(closesAt: string | null, now: Date): string {
  if (!closesAt) return "";
  const ms = new Date(closesAt).getTime() - now.getTime();
  if (ms <= 0) return "closed";
  const minutes = Math.floor(ms / 60_000);
  const days = Math.floor(minutes / 1440);
  const hours = Math.floor((minutes % 1440) / 60);
  const mins = minutes % 60;
  if (days > 0) return `${days} day${days === 1 ? "" : "s"} ${hours} h left`;
  if (hours > 0) return `${hours} h ${mins} min left`;
  return `${mins} min left`;
}

/**
 * "Sun 4 Oct, 21:00" in the browser's timezone, as every other page renders
 * times, and "Sun 4 Oct, 21:00 CEST" with the zone, which names the timezone
 * the whole page is already speaking in.
 */
export function formatEventDate(iso: string, withZone = false): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
    timeZoneName: withZone ? "short" : undefined,
  }).format(new Date(iso));
}

/** "Sun 4 Oct", no time: the bracket's compact date lines. */
export function formatEventDay(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(iso));
}

/** "20:00" in the browser's timezone: a fixed evening's start, beside its day. */
export function formatEventTime(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

/**
 * The solo page, on the mode a race pool trains for. Solo pools are the race
 * pools prefixed, and the page keeps its own default when the pool named does
 * not exist or has no seed left, so a mode without a solo counterpart still
 * lands somewhere useful.
 */
export function soloPoolName(modeKey: string): string {
  return `training_${modeKey}`;
}

/** The solo page itself, opened on that pool. */
export function soloPoolPath(modeKey: string): string {
  return `/training?pool=${soloPoolName(modeKey)}`;
}

/**
 * What a practice card says about its solo pool: how many seeds it holds, or
 * how many of them this viewer has already run. Falls back to naming the
 * thing while the counts are in flight, or for a mode with no solo pool.
 */
export function soloSeedLabel(
  pool: { available: number; played_by_user: number | null } | undefined,
): string {
  // An empty pool hands out nothing, and the solo page ignores a link to one,
  // so it reads like a mode with no solo counterpart rather than like a count.
  if (!pool || pool.available === 0) return "Solo seeds";
  const seeds = `seed${pool.available === 1 ? "" : "s"}`;
  return pool.played_by_user
    ? `${pool.played_by_user}/${pool.available} ${seeds} played`
    : `${pool.available} ${seeds} available`;
}

export interface StageTimes {
  /** The local time the evenings start at ("21:00"). */
  time: string;
  /** The single evening that starts at another time, when there is one. */
  exception: { label: string; time: string } | null;
}

/**
 * The local time the evenings start at, with the one evening that falls
 * elsewhere when exactly one does, or null when they are more scattered than
 * that (or when there is a single evening, which the announcement's plural
 * would misname). A daylight saving change inside the playoffs is enough to
 * single one evening out, so the exception is the common case, not a corner
 * one: the real season's last evening is the Sunday Europe leaves summer
 * time. Only the wall clock decides, never the zone's name: evenings at the
 * same local time either side of that change still share it. Nothing either
 * while a stage is scheduled with its players (`date_fixed` false): the page
 * then gives each fixed evening its own time.
 */
export function stageTimes(
  stages: Pick<EventStage, "label" | "date" | "date_fixed">[],
): StageTimes | null {
  // An evening agreed with its players has no place in a shared start time.
  const fixed = stages.flatMap((s) =>
    s.date_fixed && s.date !== null ? [{ label: s.label, date: s.date }] : [],
  );
  if (fixed.length < 2 || fixed.length !== stages.length) return null;
  const format = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const times = fixed.map((stage) => format.format(new Date(stage.date)));
  const counts = new Map<string, number>();
  for (const time of times) counts.set(time, (counts.get(time) ?? 0) + 1);
  if (counts.size === 1) return { time: times[0], exception: null };
  // One evening stands out only against a majority of at least two others:
  // two evenings at two times have no rule to state an exception to.
  const [common, odd] = [...counts].sort((a, b) => b[1] - a[1]);
  if (counts.size !== 2 || common[1] < 2 || odd[1] !== 1) return null;
  const stage = fixed[times.indexOf(odd[0])];
  return {
    time: common[0],
    exception: { label: stage.label, time: odd[0] },
  };
}

const LIVE_POLL_MS = 60_000;
const STAGE_DAY_POLL_MS = 300_000;
const STAGE_DAY_WINDOW_MS = 12 * 3_600_000;

/**
 * How often the page refreshes its data, or null for never: every minute while
 * a stage race is live, every five minutes around a stage's date, or around
 * any of its attached races' own `scheduled_at` (so a page left open on the
 * second evening of a two-evening match still polls), nothing otherwise (the
 * qualifier ladder moves on reload).
 */
export function pollIntervalMs(
  detail: Pick<EventDetail, "live_race" | "phase" | "stages">,
  now: Date,
): number | null {
  if (detail.phase !== "playoffs") return null;
  if (detail.live_race !== null) return LIVE_POLL_MS;
  const isNear = (iso: string) =>
    Math.abs(new Date(iso).getTime() - now.getTime()) <= STAGE_DAY_WINDOW_MS;
  const near = detail.stages.some(
    (s) =>
      (s.date !== null && isNear(s.date)) ||
      s.races.some(
        (r) => r.race.scheduled_at !== null && isNear(r.race.scheduled_at),
      ),
  );
  return near ? STAGE_DAY_POLL_MS : null;
}

const OPENING_SPREAD_MS = 10_000;
// The longest delay setTimeout holds (about 24.8 days).
const MAX_TIMEOUT_MS = 2_147_483_647;

/**
 * When an upcoming page reloads its data once, to show the seeds the opening
 * brings out: the opening plus up to ten seconds (`spread` in [0, 1)), so the
 * viewers do not all ask at the same instant. Null when the event is not
 * upcoming, or opens too far ahead for a timer.
 */
export function openingRefreshMs(
  detail: Pick<EventDetail, "phase" | "starts_at">,
  now: Date,
  spread: number,
): number | null {
  if (detail.phase !== "upcoming") return null;
  const ms =
    new Date(detail.starts_at).getTime() -
    now.getTime() +
    spread * OPENING_SPREAD_MS;
  if (ms > MAX_TIMEOUT_MS) return null;
  return Math.max(0, ms);
}

export function ordinal(n: number): string {
  const mod100 = n % 100;
  if (mod100 >= 11 && mod100 <= 13) return `${n}th`;
  switch (n % 10) {
    case 1:
      return `${n}st`;
    case 2:
      return `${n}nd`;
    case 3:
      return `${n}rd`;
    default:
      return `${n}th`;
  }
}

/**
 * A signed-out click on an event's signup button goes through Twitch first;
 * the intent it parks in sessionStorage carries the event and the time, so it
 * is honoured only on a prompt return. A return the page never mounts for (a
 * browser back served from the cache) leaves it behind, and the time bound is
 * what keeps that leftover from signing anyone up on a later visit.
 */
export const SIGNUP_INTENT_TTL_MS = 10 * 60_000;

export function encodeSignupIntent(slug: string, now: number): string {
  return JSON.stringify({ slug, at: now });
}

/** Whether a parked intent (the raw stored value) still stands for `slug` at `now`. */
export function signupIntentStands(
  raw: string | null,
  slug: string,
  now: number,
): boolean {
  if (raw === null) return false;
  let parked: unknown;
  try {
    parked = JSON.parse(raw);
  } catch {
    return false;
  }
  if (typeof parked !== "object" || parked === null) return false;
  const { slug: parkedSlug, at } = parked as { slug?: unknown; at?: unknown };
  return (
    parkedSlug === slug &&
    typeof at === "number" &&
    now - at >= 0 &&
    now - at < SIGNUP_INTENT_TTL_MS
  );
}

export interface EventBandAction {
  href: string;
  label: string;
  kind: "primary" | "twitch" | "outline";
}

export interface EventBandState {
  signal: { cls: string; text: string };
  /** The state line, without the champion: the band renders that as a user link after it. */
  line: string | null;
  actions: EventBandAction[];
  /** The viewer said they are in, and the event can still be joined. */
  signedUp: boolean;
  /** Someone is in and the event can still be joined: stack their avatars after the line. */
  showPlayers: boolean;
}

/**
 * What the home page band says about an event on the bill: a phase signal,
 * one line of state and the buttons. ``fmt`` formats an instant the viewer
 * can still act on. While the event can be joined the primary button leads
 * to the event page's signup step, or plainly to the page once the viewer
 * is in; while a playoff race runs it leads to the stream (a live caster's
 * own, else the first caster's channel) or to the race page, the event page
 * beside it.
 */
export function eventBand(
  event: EventSummary,
  fmt: (iso: string) => string,
): EventBandState {
  const page = `/events/${event.slug}`;
  const pageAction = (kind: EventBandAction["kind"]): EventBandAction => ({
    href: page,
    label: "Event page",
    kind,
  });
  const joinAction: EventBandAction[] = [
    event.my_signup
      ? pageAction("primary")
      : { href: page, label: "Take part", kind: "primary" },
  ];
  // While the event can be joined, who is in shows as avatars after the
  // line; the server already hides them while too few have committed.
  const joinable = {
    signedUp: event.my_signup,
    showPlayers: event.players > 0,
  };
  const closed = { signedUp: false, showPlayers: false };
  switch (event.phase) {
    case "upcoming":
      return {
        signal: { cls: "signal-setup", text: "Upcoming" },
        line: `Qualifier opens ${fmt(event.starts_at)}`,
        actions: joinAction,
        ...joinable,
      };
    case "qualifier":
      return {
        signal: { cls: "signal-running", text: "Qualifier open" },
        line: `Closes ${fmt(event.qualifier_ends_at)}`,
        actions: joinAction,
        ...joinable,
      };
    case "cut":
      return {
        signal: { cls: "signal-active", text: "Qualifier closed" },
        line: event.next_stage
          ? `${event.next_stage.label} on ${fmt(event.next_stage.date)}`
          : null,
        actions: [pageAction("primary")],
        ...closed,
      };
    case "playoffs": {
      const live = event.live;
      if (live) {
        const casters = live.race.casters;
        const watchUrl =
          casters.find((c) => c.is_live)?.stream_url ??
          (casters[0]
            ? `https://twitch.tv/${casters[0].user.twitch_username}`
            : null);
        return {
          signal: { cls: "signal-running", text: "Live now" },
          line: `${live.stage_label} · Race ${live.index} of ${live.races_expected}`,
          actions: [
            watchUrl
              ? { href: watchUrl, label: "Watch on Twitch", kind: "twitch" }
              : {
                  href: `/race/${live.race.id}`,
                  label: "Race page",
                  kind: "primary",
                },
            pageAction("outline"),
          ],
          ...closed,
        };
      }
      return {
        signal: { cls: "signal-running", text: "Playoffs" },
        line: event.next_stage
          ? `Next: ${event.next_stage.label} · ${fmt(event.next_stage.date)}`
          : null,
        actions: [pageAction("primary")],
        ...closed,
      };
    }
    case "finished":
      return {
        signal: { cls: "signal-finished", text: "Finished" },
        line: event.champion ? "Champion" : null,
        actions: [pageAction("primary")],
        ...closed,
      };
  }
}

export interface BracketCell {
  stage: EventStage;
  /** 0 for the stages the ladder seeds, one more per round after. */
  round: number;
  /** First tree row (0-based) and how many rows the stage spans. */
  row: number;
  span: number;
}

export interface BracketLink {
  /** The fed stage the link leads into. */
  target: BracketCell;
  /** Its sources' centres, as percentages of the target's height (the target sits at 50). */
  from: number[];
}

export interface BracketLayout {
  rounds: BracketCell[][];
  links: BracketLink[];
  /** Boxes in the first round: the tree's rows. */
  rows: number;
  final: BracketCell | null;
  newcomers: EventStage | null;
  /**
   * Four first-round boxes or more: the tree is tall enough for the evening
   * section to sit above the Champion in a side column.
   */
  tall: boolean;
}

/**
 * The bracket as a grid: one column per round (a seeded stage is round 0, a
 * fed one follows its deepest source), each round ordered so a stage's
 * sources sit next to each other, a fed stage spanning its sources' rows.
 * The newcomers' final stands apart.
 */
export function bracketLayout(stages: EventStage[]): BracketLayout {
  const tree = stages.filter((s) => s.kind !== "newcomers");
  const byKey = new Map(tree.map((s) => [s.key, s]));
  const roundOf = new Map<string, number>();
  const round = (stage: EventStage): number => {
    const known = roundOf.get(stage.key);
    if (known !== undefined) return known;
    const sources = stage.from.flatMap((k) => byKey.get(k) ?? []);
    const value = sources.length ? 1 + Math.max(...sources.map(round)) : 0;
    roundOf.set(stage.key, value);
    return value;
  };
  const depth = tree.length ? Math.max(...tree.map(round)) + 1 : 0;
  const order: EventStage[][] = Array.from({ length: depth }, () => []);
  for (let r = depth - 1; r >= 0; r--) {
    const inRound = tree.filter((s) => round(s) === r);
    const wanted = r === depth - 1 ? [] : order[r + 1].flatMap((s) => s.from);
    const placed = wanted.flatMap(
      (k) => inRound.find((s) => s.key === k) ?? [],
    );
    order[r] = [...placed, ...inRound.filter((s) => !placed.includes(s))];
  }
  const cells = new Map<string, BracketCell>();
  const links: BracketLink[] = [];
  const rounds = order.map((stagesOfRound, r) =>
    stagesOfRound.map((stage, i) => {
      const sources = stage.from.flatMap((k) => cells.get(k) ?? []);
      let cell: BracketCell;
      if (r === 0 || sources.length === 0) {
        cell = { stage, round: r, row: i, span: 1 };
      } else {
        const top = Math.min(...sources.map((c) => c.row));
        const bottom = Math.max(...sources.map((c) => c.row + c.span));
        cell = { stage, round: r, row: top, span: bottom - top };
        links.push({
          target: cell,
          from: sources.map(
            (c) => ((c.row + c.span / 2 - top) / (bottom - top)) * 100,
          ),
        });
      }
      cells.set(stage.key, cell);
      return cell;
    }),
  );
  const rows = rounds[0]?.length ?? 0;
  const finalStage = tree.find((s) => s.kind === "final");
  return {
    rounds,
    links,
    rows,
    final: finalStage ? (cells.get(finalStage.key) ?? null) : null,
    newcomers: stages.find((s) => s.kind === "newcomers") ?? null,
    tall: rows >= 4,
  };
}

/**
 * The connector into a fed stage, in a 24 by 100 box: a stub from each
 * source centre, a spine joining them, and the way out at mid-height.
 */
export function linkPath(from: number[]): string {
  if (from.length === 1 && from[0] === 50) return "M0 50 H24";
  const stubs = from.map((y) => `M0 ${y} H12`).join(" ");
  const ys = [...from, 50];
  return `${stubs} M12 ${Math.min(...ys)} V${Math.max(...ys)} M12 50 H24`;
}

export interface PlayoffsPlan {
  /** Runners the ladder sends to the playoffs: the seeded stages' seats. */
  places: number;
  /** The rounds scheduled with their players, "quarters and semis", or null. */
  agreed: string | null;
  /** The stages on a date the config fixes, newcomers' final aside, in order. */
  fixed: {
    key: string;
    label: string;
    kind: EventStage["kind"];
    date: string;
  }[];
}

const KIND_PLURAL: Record<Exclude<EventStage["kind"], "round">, string> = {
  quarter: "quarters",
  semi: "semis",
  final: "final",
  newcomers: "newcomers' final",
};

/** A round played before the quarters, named after its seats: "round of 32". */
function roundName(stages: EventStage[]): string {
  const seats = stages
    .filter((s) => s.kind === "round")
    .reduce((n, s) => n + s.field.length, 0);
  return `round of ${seats}`;
}

/** What the format block's playoffs paragraph says about the bracket. */
export function playoffsPlan(stages: EventStage[]): PlayoffsPlan {
  const tree = stages.filter((s) => s.kind !== "newcomers");
  const places = tree
    .filter((s) => s.from.length === 0)
    .reduce((n, s) => n + s.field.length, 0);
  const kinds = [
    ...new Set(
      tree
        .filter((s) => !s.date_fixed)
        .map((s) =>
          s.kind === "round" ? roundName(tree) : KIND_PLURAL[s.kind],
        ),
    ),
  ];
  const agreed =
    kinds.length === 0
      ? null
      : kinds.length === 1
        ? kinds[0]
        : `${kinds.slice(0, -1).join(", ")} and ${kinds.at(-1)}`;
  const fixed = tree.flatMap((s) =>
    s.date_fixed && s.date !== null
      ? [{ key: s.key, label: s.label, kind: s.kind, date: s.date }]
      : [],
  );
  return { places, agreed, fixed };
}

/**
 * The meta line of a qualified group's box: the stage's label, with its date
 * when it has one. A round's stage labelled like its box title ("Group A")
 * would repeat it, so it names its round instead ("Round of 32").
 */
export function qualifiedMeta(
  stage: EventStage,
  title: string,
  stages: EventStage[],
  formatDate: (iso: string) => string,
): string {
  const round = roundName(stages);
  const name =
    stage.kind === "round" && stage.label === title
      ? round.charAt(0).toUpperCase() + round.slice(1)
      : stage.label;
  return stage.date ? `${name} on ${formatDate(stage.date)}` : name;
}
