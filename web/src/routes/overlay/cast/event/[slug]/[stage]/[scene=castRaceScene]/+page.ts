import { fetchStageCurrentRace, type StageCurrentRace } from "$lib/api";
import { redirect } from "@sveltejs/kit";
import { parseCastParams } from "$lib/cast/params";
import { followStep, followTarget } from "$lib/cast/follow";
import type { PageLoad } from "./$types";

// A race scene keyed by an event stage only resolves: it hands over to the
// same scene of the stage's current race, which keeps following the stage
// from there. With no race to show yet, or no answer at all, the page shows
// the scene's empty plate and asks again: never an error page on air.
export const load: PageLoad = async ({ params, url, fetch }) => {
  const castParams = parseCastParams(url);
  const { slug, stage, scene } = params;

  let answer: StageCurrentRace | null;
  try {
    answer = await fetchStageCurrentRace(slug, stage, fetch);
  } catch {
    answer = null;
  }
  // `hold` names a race whose scene just fell back here because it would not
  // load: the page's poll retries it a beat later, not this load at once.
  const { navigateTo } = followStep(null, null, answer);
  if (navigateTo && navigateTo !== url.searchParams.get("hold")) {
    throw redirect(
      307,
      followTarget(navigateTo, scene, url.searchParams, { slug, stage }),
    );
  }

  return { castParams, scene, slug, stage };
};
