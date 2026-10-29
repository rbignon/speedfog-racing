import { fetchSpeedrunSeed, SeedLookupError } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, url, fetch }) => {
  try {
    const seed = await fetchSpeedrunSeed(params.seed, fetch);
    // The run the page was opened on (`?run=<id>`), ticked on arrival.
    return { seed, run: url.searchParams.get("run") };
  } catch (e) {
    // No page under this ID: the not-found page, which says why. Anything
    // else (the server or the network failing) is not a missing seed.
    if (e instanceof SeedLookupError) {
      throw error(
        404,
        e.kind === "unknown"
          ? "Seed not found"
          : `Several seeds start with ${params.seed}. Use more of the seed ID.`,
      );
    }
    throw e;
  }
};
