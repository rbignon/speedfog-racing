import { fetchSpeedrunSeed } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, url, fetch }) => {
  try {
    const seed = await fetchSpeedrunSeed(params.seed, fetch);
    // The run the page was opened on (`?run=<id>`), ticked on arrival.
    return { seed, run: url.searchParams.get("run") };
  } catch {
    throw error(404, "Seed not found");
  }
};
