import { getInvite } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ params }) => {
  try {
    const invite = await getInvite(params.token);
    return { invite };
  } catch {
    throw error(404, "Invite not found");
  }
};
