import { fetchEvent, fetchUserProfile, type UserProfile } from "$lib/api";
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

  // The scene has no race, so the casters come from the URL. A username that
  // resolves to nobody leaves that cam unnamed rather than failing the scene.
  const casters = await Promise.all(
    castParams.casters.map(async (name): Promise<UserProfile | null> => {
      if (!name) return null;
      try {
        return await fetchUserProfile(name, fetch);
      } catch {
        return null;
      }
    }),
  );

  return { event, stage, casters, castParams };
};
