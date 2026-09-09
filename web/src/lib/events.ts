import type {
  EventDetail,
  EventFact,
  EventPhase,
  EventQualifierRace,
  EventStage,
} from "$lib/api";

export type EventBlock =
  | "format"
  | "take_part"
  | "seeds"
  | "ladder_qualified"
  | "qualified_ladder"
  | "live"
  | "bracket_ladder"
  | "rules";

/**
 * Which blocks the page shows, top to bottom, for a phase. The take-part and
 * bracket blocks each carry the rules card in their right column, so the
 * standalone rules block only appears in the cut phase, which shows neither.
 */
export function blockOrder(phase: EventPhase): EventBlock[] {
  switch (phase) {
    case "upcoming":
    case "qualifier":
      return ["format", "take_part", "seeds", "ladder_qualified"];
    case "cut":
      return ["qualified_ladder", "rules"];
    case "playoffs":
      return ["live", "bracket_ladder"];
    case "finished":
      return ["bracket_ladder"];
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
 * One entry per seed slot of a mode, in slot order: the attached race, or
 * null for a slot that has none (before the qualifier opens, or a voided seed).
 */
export function seedSlots(
  races: EventQualifierRace[],
  seedsPerMode: number,
): (EventQualifierRace | null)[] {
  return Array.from(
    { length: seedsPerMode },
    (_, i) => races.find((r) => r.index === i + 1) ?? null,
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

type TitleInput = Pick<EventDetail, "live_race" | "next_stage" | "stages">;

/** "Live now · Semi B" while a stage race runs, "Up next · Semi A · <date>" otherwise. */
export function racesSectionTitle(
  detail: TitleInput,
  formatDate: (iso: string) => string,
): string {
  if (detail.live_race) {
    const stage = liveStage(detail);
    return stage ? `Live now · ${stage.label}` : "Live now";
  }
  if (detail.next_stage) {
    return `Up next · ${detail.next_stage.label} · ${formatDate(detail.next_stage.date)}`;
  }
  return "Races";
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
