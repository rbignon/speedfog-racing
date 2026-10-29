import { redirect } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

// The speedrun.fog tab became the /speedrun page.
export const load: PageLoad = ({ url }) => {
  if (url.searchParams.get("tab") === "speedrun") {
    redirect(307, "/speedrun");
  }
};
