/**
 * What the setup panel feeds the OBS collection generator (`./obs`): the
 * runners each file seats, its file name, and the download itself.
 */

import type { EventFieldSlot, RaceDetail, User } from "$lib/api";
import type { ObsRunner } from "./obs";
import { resolveSlots } from "./params";

/** The talk scene's stage a race attached to an event names in its slot
 * (`<stage>:<n>`, a showcase's key the same way). A qualifier slot
 * (`qualifier:<mode>:<n>`) names none: talk introduces playoff evenings. */
export function stageKeyOf(slot: string | null): string {
  if (!slot || slot.startsWith("qualifier:")) return "";
  const end = slot.lastIndexOf(":");
  return end < 0 ? "" : slot.slice(0, end);
}

function runnerOf(user: User): ObsRunner {
  return {
    username: user.twitch_username,
    name: user.twitch_display_name || user.twitch_username,
  };
}

/** The race's seats as its scenes would fill them: the pins, then the
 * runners nobody pinned in join order, the same `resolveSlots` the panel's
 * "(auto: ...)" options name. */
export function raceSeats(
  race: RaceDetail,
  pins: (string | null)[],
): (ObsRunner | null)[] {
  const pool = race.participants.map((p) => ({
    twitch_username: p.user.twitch_username,
    color_index: p.color_index,
    runner: runnerOf(p.user),
  }));
  return resolveSlots(pool, pins).map((p) => p?.runner ?? null);
}

/** A stage's seats from its declared field, the same for every race of the
 * stage: the pins, then the field in its own order. A seat with no runner
 * yet seats nobody, nor does a forfeited one (its runner races none of the
 * stage's races). */
export function stageSeats(
  field: EventFieldSlot[],
  pins: (string | null)[],
): (ObsRunner | null)[] {
  const pool = field.flatMap((slot, i) =>
    slot.user && !slot.forfeited
      ? [
          {
            twitch_username: slot.user.twitch_username,
            color_index: i,
            runner: runnerOf(slot.user),
          },
        ]
      : [],
  );
  return resolveSlots(pool, pins).map((p) => p?.runner ?? null);
}

/** Whether every seat of the field has its runner (a fed seat gets one once
 * its source stage is over; a forfeited seat is settled, nobody replaces it). */
export function stageFieldSettled(field: EventFieldSlot[]): boolean {
  return field.every((slot) => slot.user !== null);
}

/** `speedfog-<event>-<stage>.json` for a match; for a race,
 * `speedfog-<event>-<stage>-<n>.json` on a stage or showcase slot, else
 * `speedfog-race-<first 8 characters of its id>.json`. */
export function obsFileName(kind: "race" | "match", race: RaceDetail): string {
  const stage = stageKeyOf(race.event_slot);
  if (!stage || !race.event_slug || !race.event_slot) {
    return `speedfog-race-${race.id.slice(0, 8)}.json`;
  }
  if (kind === "match") return `speedfog-${race.event_slug}-${stage}.json`;
  const n = race.event_slot.slice(stage.length + 1);
  return `speedfog-${race.event_slug}-${stage}-${n}.json`;
}

/** Save `data` as a pretty-printed JSON file, as OBS writes its own. */
export function downloadJson(fileName: string, data: unknown): void {
  const blob = new Blob([JSON.stringify(data, null, 2)], {
    type: "application/json",
  });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = fileName;
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}
