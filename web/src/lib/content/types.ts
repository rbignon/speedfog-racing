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

/** A video shown as a thumbnail linking out to its site: YouTube or a Twitch clip. */
export type ContentVideo =
  | {
      /** YouTube video id (11 chars). */
      youtubeId: string;
      /** Optional start offset in seconds. */
      start?: number;
      twitchClipId?: never;
      thumbnail?: never;
    }
  | {
      /** Twitch clip slug, the last segment of the clip URL (twitch.tv/<channel>/clip/<slug> or clips.twitch.tv/<slug>). */
      twitchClipId: string;
      /** Clip thumbnail URL, copied from the clip page's og:image meta tag: unlike YouTube's, it can't be derived from the id. Prefer the `-480x272.jpg` variant (swap the `-1920x1080.jpg` suffix), the same size class as YouTube's thumbnail and about 7x lighter. */
      thumbnail: string;
      youtubeId?: never;
      start?: never;
    };

export interface ContentItem {
  /** Stable kebab-case identifier, used for seen-recently tracking. */
  id: string;
  kind: ContentKind;
  /** Required for kinds "tip" and "game_change": drives the ticker's newcomer/experienced targeting (the Game Changes page ignores it). Absent on skips. */
  level?: TipLevel;
  /** Only for kind "game_change". */
  category?: GameChangeCategory;
  /** Fine-grained zone ids from the seed graph's zones list (e.g. academy_rooftops) the item is about: it matches a cluster when any of them belongs to the cluster's zone composition. A zone that only belongs to boss clusters has no zone sheet, so it matches nothing there. Required for skips, optional for tips and game changes. */
  zoneIds?: string[];
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
