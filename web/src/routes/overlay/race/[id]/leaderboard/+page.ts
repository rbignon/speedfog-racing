import { fetchRace } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, fetch }) => {
  try {
    const race = await fetchRace(params.id, fetch);
    return { race };
  } catch {
    throw error(404, "Race not found");
  }
};
