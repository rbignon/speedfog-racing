export type ContentKind = "tip" | "game_change" | "skip";
export type TipLevel = "beginner" | "advanced";
/** Skip execution difficulty, rendered as a 1-5 frog rating in the Zone Codex. */
export type SkipDifficulty = 1 | 2 | 3 | 4 | 5;

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

export interface ContentVideo {
  /** YouTube video id (11 chars). */
  youtubeId: string;
  /** Optional start offset in seconds. */
  start?: number;
}

export interface ContentItem {
  /** Stable kebab-case identifier, used for seen-recently tracking. */
  id: string;
  kind: ContentKind;
  /** Only for kind "tip". */
  level?: TipLevel;
  /** Only for kind "game_change". */
  category?: GameChangeCategory;
  /** Fine-grained zone id from the seed graph's zones list (e.g. academy_rooftops); required for skips, optional zone-scoping for tips. */
  zoneId?: string;
  /** Only for kind "skip", where it is required. */
  difficulty?: SkipDifficulty;
  video?: ContentVideo;
  /** Author credit for community-contributed videos. */
  credit?: string;
  /** Short label shown as the tip heading. */
  title: string;
  /** One or two sentences, shown in the ticker and accordions. Required (non-empty) for kinds "tip" and "game_change"; may be empty for "skip", whose title can carry all the information. */
  short: string;
  /** Longer prose for the Game Changes page; falls back to `short`. */
  body?: string;
  /** Pool keys (snake_case) this item is specific to; omitted = all pools. */
  pools?: string[];
}
