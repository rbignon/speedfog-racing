import { fetchEvent } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

// A slate reads its stage and nothing else: no caster, no cam and no runner
// video, so its URL carries no parameter.
export const load: PageLoad = async ({ params, fetch }) => {
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
  return { event, stage, scene: params.scene };
};
