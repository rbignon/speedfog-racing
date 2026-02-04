import { fetchRace } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params }) => {
  try {
    const race = await fetchRace(params.id);
    return { race };
  } catch {
    throw error(404, "Race not found");
  }
};
