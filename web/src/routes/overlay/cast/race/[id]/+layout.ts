import { fetchRace, fetchEvent } from "$lib/api";
import { error, redirect } from "@sveltejs/kit";
import { parseCastParams } from "$lib/cast/params";
import { fallbackTarget } from "$lib/cast/follow";
import type { LayoutLoad } from "./$types";

export const load: LayoutLoad = async ({ params, url, fetch }) => {
  const castParams = parseCastParams(url);

  let race;
  try {
    race = await fetchRace(params.id, fetch);
  } catch {
    race = null;
  }
  if (!race) {
    // A scene following a stage (reloaded in place after a hand-over, or
    // handed a race that went away) falls back to the stage's waiting plate,
    // which retries this race, rather than an error page on air.
    const follow = castParams.follow;
    if (follow) {
      const scene = url.pathname.split("/").pop() ?? "";
      throw redirect(
        307,
        fallbackTarget(params.id, scene, url.searchParams, follow),
      );
    }
    throw error(404, "Race not found");
  }

  // The co-brand names whichever event the caster points this scene at
  // (`?event=<slug>`), never the race's own event by default: a URL says
  // what it shows, and one with no `event` shows no co-brand (the setup
  // panel prefills the race's own event into the URLs it builds). A wrong or
  // stale slug degrades to no partner rather than failing the whole scene,
  // since the race itself is still perfectly valid.
  let partnerName: string | null = null;
  if (castParams.event) {
    try {
      partnerName = (await fetchEvent(castParams.event, fetch)).partner_name;
    } catch {
      partnerName = null;
    }
  }

  return { race, castParams, partnerName };
};
