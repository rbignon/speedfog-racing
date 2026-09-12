import type {
  EventDetail,
  EventFact,
  EventMode,
  EventPhase,
  EventStage,
  User,
} from "$lib/api";

export type EventBlock =
  | "intro"
  | "format"
  | "take_part"
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
      return ["intro", "format", "take_part", "seeds", "ladder_qualified"];
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
      lines: ["Own final", formatDay(newcomers.date)],
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
  "current_stage_key" | "next_stage" | "stages"
>;

/**
 * The evening whose races the bracket block lists: today's stage during the
 * playoffs, else the next one, else the last one once everything ran.
 */
export function shownStage(detail: ShownStageInput): EventStage | null {
  const key =
    detail.current_stage_key ??
    detail.next_stage?.key ??
    detail.stages.at(-1)?.key;
  return detail.stages.find((s) => s.key === key) ?? null;
}

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
      meta: formatDate(stage.date),
    };
  }
  const started = stage.races.some((r) => r.race.status !== "setup");
  if (!started || new Date(stage.date).getTime() > now.getTime()) {
    return {
      signal: { cls: "signal-setup", text: "Up next" },
      meta: formatDate(stage.date),
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

export interface PracticeHint {
  kind: "gap" | "done";
  /** The modes never opened, for a gap; empty once every seed is spent. */
  modes: EventMode[];
}

/**
 * What to tell a signed-in runner about practising, read from the seeds they
 * have touched: the modes they have never opened, or, once every seed is
 * spent, nothing left to run here. Null while they are mid-qualifier with a
 * seed still to play, and for a viewer with no results at all (signed out, or
 * an event whose seeds are not attached yet), which is the page's quiet case.
 */
export function practiceHint(
  detail: Pick<EventDetail, "modes" | "qualifier_races" | "seeds_per_mode">,
): PracticeHint | null {
  const mine = detail.qualifier_races.filter((r) => r.my_result !== null);
  if (mine.length === 0) return null;
  const started = detail.modes
    .map((mode) => ({ mode, races: mine.filter((r) => r.mode === mode.key) }))
    .filter((m) => m.races.length > 0);
  // Registered on a seed and never started counts as never run: that is the
  // runner the hint is for, not the one mid-run.
  const gap = started
    .filter((m) =>
      m.races.every(
        (r) =>
          r.my_result?.status === "not_played" ||
          r.my_result?.status === "joined",
      ),
    )
    .map((m) => m.mode);
  if (gap.length > 0) return { kind: "gap", modes: gap };
  // Every seed of the event, not merely every seed out: an organiser attaches
  // them one at a time, and nothing is spent about a seed card still empty.
  const everySeed = detail.modes.length * detail.seeds_per_mode;
  const allRun =
    mine.length === everySeed &&
    mine.every((r) => r.my_result?.status === "done");
  return allRun ? { kind: "done", modes: [] } : null;
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
 * same local time either side of that change still share it.
 */
export function stageTimes(
  stages: Pick<EventStage, "label" | "date">[],
): StageTimes | null {
  if (stages.length < 2) return null;
  const format = new Intl.DateTimeFormat("en-GB", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  });
  const times = stages.map((stage) => format.format(new Date(stage.date)));
  const counts = new Map<string, number>();
  for (const time of times) counts.set(time, (counts.get(time) ?? 0) + 1);
  if (counts.size === 1) return { time: times[0], exception: null };
  // One evening stands out only against a majority of at least two others:
  // two evenings at two times have no rule to state an exception to.
  const [common, odd] = [...counts].sort((a, b) => b[1] - a[1]);
  if (counts.size !== 2 || common[1] < 2 || odd[1] !== 1) return null;
  const stage = stages[times.indexOf(odd[0])];
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
 * a stage race is live, every five minutes around a stage's date so an open
 * page sees the evening's race go live, nothing otherwise (the qualifier
 * ladder moves on reload).
 */
export function pollIntervalMs(
  detail: Pick<EventDetail, "live_race" | "phase" | "stages">,
  now: Date,
): number | null {
  if (detail.phase !== "playoffs") return null;
  if (detail.live_race !== null) return LIVE_POLL_MS;
  const near = detail.stages.some(
    (s) =>
      Math.abs(new Date(s.date).getTime() - now.getTime()) <=
      STAGE_DAY_WINDOW_MS,
  );
  return near ? STAGE_DAY_POLL_MS : null;
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
