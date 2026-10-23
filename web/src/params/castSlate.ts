import type { ParamMatcher } from "@sveltejs/kit";

/** The slates: the intro, pause and end cards of an evening. Listed here
 * rather than imported from $lib/cast/layout: param matchers load with the
 * app's entry, on every page. */
export const match = ((param: string): param is "intro" | "pause" | "end" =>
  ["intro", "pause", "end"].includes(param)) satisfies ParamMatcher;
