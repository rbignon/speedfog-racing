import { fetchDailyByDate, fetchRecentDailies } from "$lib/api";
import { error } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

const DATE_RE = /^\d{4}-\d{2}-\d{2}$/;

export const load: PageLoad = async ({ params, fetch }) => {
  if (!DATE_RE.test(params.date)) {
    throw error(404, "Daily seed not found");
  }
  try {
    const [race, recent] = await Promise.all([
      fetchDailyByDate(params.date, fetch),
      fetchRecentDailies(7, fetch),
    ]);
    return { race, recent };
  } catch {
    throw error(404, "Daily seed not found");
  }
};
