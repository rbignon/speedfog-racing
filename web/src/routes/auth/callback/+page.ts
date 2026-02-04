import { redirect } from "@sveltejs/kit";
import type { PageLoad } from "./$types";

export const load: PageLoad = async ({ url }) => {
  const token = url.searchParams.get("token");
  const error = url.searchParams.get("error");

  if (error) {
    // Redirect to home with error
    throw redirect(302, `/?error=${encodeURIComponent(error)}`);
  }

  if (!token) {
    // No token provided
    throw redirect(302, "/?error=no_token");
  }

  // Pass token to the page component for client-side processing
  return { token };
};
