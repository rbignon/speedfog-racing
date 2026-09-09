import type { EventDetail, EventFact, EventPhase, EventStage } from "$lib/api";

export type EventBlock =
  | "format"
  | "take_part"
  | "seeds"
  | "ladder_qualified"
  | "live"
  | "bracket_ladder";

/**
 * Which blocks the page shows, top to bottom, for a phase. The take-part
 * block carries the qualifier rules, the bracket block the playoff rules and
 * the next (or current) evening's races; from the cut on the bracket replaces
 * the qualified column, the ladder staying under it.
 */
export function blockOrder(phase: EventPhase): EventBlock[] {
  switch (phase) {
    case "upcoming":
    case "qualifier":
      return ["format", "take_part", "seeds", "ladder_qualified"];
    case "cut":
    case "finished":
      return ["bracket_ladder"];
    case "playoffs":
      return ["live", "bracket_ladder"];
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

type TitleInput = Pick<EventDetail, "live_race"> & ShownStageInput;

/**
 * The races section title, always about the stage whose races it lists:
 * "Live now · Semi B" while one of its races runs, "Up next · Semi A · <date>"
 * while its evening is still ahead, its bare label otherwise (between two of
 * its races, or once the last evening ran).
 */
export function racesSectionTitle(
  detail: TitleInput,
  formatDate: (iso: string) => string,
  now: Date,
): string {
  const stage = shownStage(detail);
  if (!stage) return "Races";
  const liveHere =
    detail.live_race !== null &&
    stage.races.some((r) => r.race.id === detail.live_race?.id);
  if (liveHere) return `Live now · ${stage.label}`;
  if (new Date(stage.date).getTime() > now.getTime()) {
    return `Up next · ${stage.label} · ${formatDate(stage.date)}`;
  }
  return stage.label;
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

/** "Sun 4 Oct, 21:00" in the browser's timezone, as every other page renders times. */
export function formatEventDate(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(new Date(iso));
}

/** "Sun 4 Oct", no time: the bracket's compact per-stage meta line. */
export function formatEventDay(iso: string): string {
  return new Intl.DateTimeFormat("en-GB", {
    weekday: "short",
    day: "numeric",
    month: "short",
  }).format(new Date(iso));
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
