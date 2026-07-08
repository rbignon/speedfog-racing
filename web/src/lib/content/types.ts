export type ContentKind = "tip" | "game_change";
export type TipLevel = "beginner" | "advanced";

export const GAME_CHANGE_CATEGORIES = [
  "start",
  "traversal",
  "combat",
  "economy",
  "qol",
] as const;
export type GameChangeCategory = (typeof GAME_CHANGE_CATEGORIES)[number];

export const CATEGORY_LABELS: Record<GameChangeCategory, string> = {
  start: "Your start",
  traversal: "Traversal and the route",
  combat: "Combat and bosses",
  economy: "Items and economy",
  qol: "Quality of life",
};

export interface ContentItem {
  /** Stable kebab-case identifier, used for seen-recently tracking. */
  id: string;
  kind: ContentKind;
  /** Only for kind "tip". */
  level?: TipLevel;
  /** Only for kind "game_change". */
  category?: GameChangeCategory;
  /** Short label shown as the tip heading. */
  title: string;
  /** One or two sentences, shown in the ticker and accordions. */
  short: string;
  /** Longer prose for the Game Changes page; falls back to `short`. */
  body?: string;
  /** Pool keys (snake_case) this item is specific to; omitted = all pools. */
  pools?: string[];
}
