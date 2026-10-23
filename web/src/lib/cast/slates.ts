/** What the intro and end slates compute from their stage. */

import type { EventShowcase, EventStage, EventStageEntry } from "$lib/api";
import { formatEventDay, stageGoesOn } from "$lib/events";
import { formatStartsIn } from "./clock";

export interface SlateClock {
  /** The small caption above the text ("Starts in"), when it has one. */
  label: string | null;
  text: string;
}

/**
 * The intro's line under the stage at `nowMs`: a countdown to the stage's
 * start, "Starting soon" once that start has passed, the day alone while only
 * the day is set (the date then stands at noon UTC, which no countdown should
 * aim at), nothing without a date.
 */
export function introClock(
  date: string | null,
  timeSet: boolean,
  nowMs: number,
): SlateClock | null {
  if (!date) return null;
  if (!timeSet) return { label: null, text: formatEventDay(date) };
  const ms = Date.parse(date) - nowMs;
  return ms > 0
    ? { label: "Starts in", text: formatStartsIn(ms) }
    : { label: null, text: "Starting soon" };
}

export interface EndHeadline {
  title: "Qualified" | "Champion" | "Winner";
  /** The stage is still being raced: the runners can still change. */
  provisional: boolean;
  /** Who the end slate puts up front, each with the stage their place goes
   * on to (null when none does). */
  runners: { entry: EventStageEntry; next: string | null }[];
}

type EndStage = Pick<
  EventStage | EventShowcase,
  "kind" | "advance" | "complete" | "settled_results"
>;

/**
 * The end slate's runners, from the finished races' standings: the runners
 * going on (`advance` of them, by the standings panel's own rule, so the two
 * never disagree), or, on a stage nobody goes on from, its winner alone: the
 * champion of a final, the winner of anything else (a showcase).
 */
export function endHeadline(
  stage: EndStage,
  nextLabels: (string | null)[],
): EndHeadline {
  const results = stage.settled_results;
  const provisional = !stage.complete && results.length > 0;
  if (stage.advance === null) {
    return {
      title: stage.kind === "final" ? "Champion" : "Winner",
      provisional,
      runners: results.slice(0, 1).map((entry) => ({ entry, next: null })),
    };
  }
  const { advance, complete } = stage;
  return {
    title: "Qualified",
    provisional,
    runners: results.flatMap((entry, i) =>
      stageGoesOn(entry, i, advance, complete)
        ? [{ entry, next: nextLabels[i] ?? null }]
        : [],
    ),
  };
}
