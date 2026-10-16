import type { ParamMatcher } from "@sveltejs/kit";

/** The cast scenes that show one race: every scene but `talk`. */
export const match = ((
  param: string,
): param is "quad" | "focus" | "duel" | "metro" | "browser" =>
  ["quad", "focus", "duel", "metro", "browser"].includes(
    param,
  )) satisfies ParamMatcher;
