import { fetchRace } from "$lib/api";
import { error } from "@sveltejs/kit";
import { parseCastParams } from "$lib/cast/params";
import type { LayoutLoad } from "./$types";

export const load: LayoutLoad = async ({ params, url, fetch }) => {
  try {
    const race = await fetchRace(params.id, fetch);
    return { race, castParams: parseCastParams(url) };
  } catch {
    throw error(404, "Race not found");
  }
};
