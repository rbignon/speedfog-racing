import { fetchRace, fetchEvent } from "$lib/api";
import { error, redirect } from "@sveltejs/kit";
import { parseCastParams } from "$lib/cast/params";
import { fallbackTarget } from "$lib/cast/follow";
import type { LayoutLoad } from "./$types";

// Partner names by event slug, kept for the page's life: a scene following a
// stage re-runs this load at every hand-over, and the event detail it reads
// them from is heavy. Only answers are kept, so a failed read is retried by
// the next load; an OBS refresh starts afresh.
const partnerNames = new Map<string, string | null>();

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
      const scene = url.pathname.split("/").filter(Boolean).pop() ?? "";
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
  const slug = castParams.event;
  if (slug && partnerNames.has(slug)) {
    partnerName = partnerNames.get(slug) ?? null;
  } else if (slug) {
    try {
      partnerName = (await fetchEvent(slug, fetch)).partner_name;
      partnerNames.set(slug, partnerName);
    } catch {
      partnerName = null;
    }
  }

  return { race, castParams, partnerName };
};
