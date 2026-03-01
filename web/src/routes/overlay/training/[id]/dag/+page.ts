import { fetchTrainingSession } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params }) => {
  try {
    const session = await fetchTrainingSession(params.id);
    return { session };
  } catch {
    throw error(404, "Training session not found");
  }
};
