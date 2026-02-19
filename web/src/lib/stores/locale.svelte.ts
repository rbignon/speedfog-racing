/**
 * Locale store — resolves effective locale from user preference or browser language.
 */

import { auth } from "$lib/stores/auth.svelte";

/**
 * Get the effective locale for the current user.
 * Priority: user DB locale → browser language → "en"
 *
 * Note: browser-detected locale is not validated against available translations.
 * The server handles unknown locales gracefully by returning English data.
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
