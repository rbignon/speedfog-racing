import { fetchTodayDaily } from "$lib/api";
import { redirect } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

/**
 * Bare /daily route: redirect to today's archive page when a daily is
 * running, otherwise fall through to the empty-state component.
 */
export const load: PageLoad = async ({ fetch }) => {
  try {
    const daily = await fetchTodayDaily(fetch);
    if (daily.daily_date) {
      throw redirect(307, `/daily/${daily.daily_date}`);
    }
  } catch (e) {
    // SvelteKit redirects are thrown; let them propagate.
    if (
      e &&
      typeof e === "object" &&
      "status" in e &&
      (e as { status: number }).status === 307
    ) {
      throw e;
    }
    return { missing: true } as const;
  }
  return { missing: true } as const;
};
