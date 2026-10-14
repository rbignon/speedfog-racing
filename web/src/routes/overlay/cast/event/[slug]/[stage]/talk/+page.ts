import { fetchEvent, fetchUserProfile } from "$lib/api";
import { error } from "@sveltejs/kit";
import { parseCastParams } from "$lib/cast/params";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, url, fetch }) => {
  const castParams = parseCastParams(url);
  let event;
  try {
    event = await fetchEvent(params.slug, fetch);
  } catch {
    throw error(404, "Event not found");
  }
  const stage = [...event.stages, ...event.showcases].find(
    (s) => s.key === params.stage,
  );
  if (!stage) throw error(404, "Stage not found");

  // The scene has no race, so the casters come from the URL. A registered
  // caster shows under their display name; a name the site does not know is
  // printed as written, like the race scenes print it: a caster needs no
  // account here.
  const casters = (await Promise.all(
    castParams.casters.map(async (name): Promise<string | null> => {
      if (!name) return null;
      try {
        const profile = await fetchUserProfile(name, fetch);
        return profile.twitch_display_name || profile.twitch_username;
      } catch {
        return name;
      }
    }),
  )) as [string | null, string | null];

  return { event, stage, casters, castParams };
};
