/**
 * Locale store — resolves effective locale from user preference.
 *
 * User.locale is always set (initialized from browser language on first login),
 * so this is a simple accessor with a fallback for unauthenticated contexts.
 */

import { auth } from "$lib/stores/auth.svelte";

/**
 * Get the effective locale for the current user.
 * Falls back to browser language for unauthenticated spectators.
 */
export function getEffectiveLocale(): string {
  if (auth.user?.locale) {
    return auth.user.locale;
  }
  if (typeof navigator !== "undefined") {
    const lang = navigator.language?.split("-")[0];
    if (lang && lang !== "en") {
      return lang;
    }
  }
  return "en";
}
