import type { RaceStatus, StageCurrentRace } from "$lib/api";
import { followParam } from "./params";

/** How often a scene following a stage asks for its current race, while the
 * race it shows is not running. */
export const FOLLOW_POLL_MS = 5000;

export type FollowStep = { navigateTo: string | null; keepPolling: boolean };

/**
 * What a scene following a stage does with one answer about the stage's
 * current race. `shownRaceId` and `shownStatus` are the race it shows, null
 * on the stage-keyed route before any race; `answer` is null when the fetch
 * failed, which only means "ask again". `navigateTo` names the race to move
 * to (build its URL with `followTarget`).
 *
 * A running race is never left nor polled for: nothing can replace it before
 * it ends, and a scene flipping away mid-race is the one outcome the follow
 * mode must never produce. Polling stops for good once the stage is done on
 * the race shown.
 */
export function followStep(
  shownRaceId: string | null,
  shownStatus: RaceStatus | null,
  answer: StageCurrentRace | null,
): FollowStep {
  if (shownStatus === "running") {
    return { navigateTo: null, keepPolling: false };
  }
  if (!answer) return { navigateTo: null, keepPolling: true };
  const onShown = answer.race_id !== null && answer.race_id === shownRaceId;
  return {
    navigateTo: answer.race_id !== null && !onShown ? answer.race_id : null,
    keepPolling: !(answer.done && onShown),
  };
}

/** The same scene of race `raceId`, with the query string kept as is and
 * `follow` set to the stage being followed. */
export function followTarget(
  raceId: string,
  scene: string,
  search: URLSearchParams,
  follow: { slug: string; stage: string },
): string {
  const query = new URLSearchParams(search);
  query.set("follow", followParam(follow.slug, follow.stage));
  return `/overlay/cast/race/${encodeURIComponent(raceId)}/${scene}?${query}`;
}
