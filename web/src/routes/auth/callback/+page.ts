import { redirect } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ url }) => {
  const code = url.searchParams.get("code");
  const error = url.searchParams.get("error");

  if (error) {
    // Redirect to home with error
    throw redirect(302, `/?error=${encodeURIComponent(error)}`);
  }

  if (!code) {
    // No code provided
    throw redirect(302, "/?error=no_code");
  }

  // Pass code to the page component for client-side exchange
  return { code };
};
