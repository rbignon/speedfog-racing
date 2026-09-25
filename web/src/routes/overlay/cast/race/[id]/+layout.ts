import { fetchRace, fetchEvent } from "$lib/api";
import { error } from "@sveltejs/kit";
import { parseCastParams } from "$lib/cast/params";
import type { LayoutLoad } from "./$types";

export const load: LayoutLoad = async ({ params, url, fetch }) => {
  const castParams = parseCastParams(url);

  let race;
  try {
    race = await fetchRace(params.id, fetch);
  } catch {
    throw error(404, "Race not found");
  }

  // The co-brand names whichever event the caster points this scene at
  // (`?event=<slug>`), not the race's own event_id: there is no client
  // endpoint that resolves that id to an EventDetail. A wrong or stale slug
  // degrades to no partner rather than failing the whole scene, since the
  // race itself is still perfectly valid.
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
