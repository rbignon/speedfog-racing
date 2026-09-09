import { fetchEvent } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params, fetch }) => {
  try {
    const detail = await fetchEvent(params.slug, fetch);
    return { detail };
  } catch {
    throw error(404, "Event not found");
  }
};
