import type { CastSceneId } from "./layout";

/**
 * Everything the setup panel knows that a cast scene's URL might carry.
 * Which fields actually turn into query params depends on the scene: see
 * `buildCastUrl`.
 */
export interface CastUrlOpts {
  /** Which race's scenes these are. Required for every scene but `talk`. */
  raceId?: string;
  /** Twitch usernames wanted in POV holes 1 to 4; null (or absent) leaves
   * that hole to the scene's own join-order fallback. Ignored on `talk`,
   * which seats nobody. */
  slots?: (string | null)[];
  /** How many caster cams the desk shows: 0, 1 or 2. */
  cams: number;
  /** The two caster usernames for c1/c2; either half may be null. */
  casters?: [string | null, string | null];
  /** Delay in seconds, race scenes only. 0 means no delay and is dropped. */
  delayS?: number;
  /** Which slot (1 to 4) is the hero POV. Read only on the `focus` scene. */
  focus?: number;
  /** The event whose co-brand a race scene shows. Null/absent shows none. */
  event?: string | null;
  /** The event slug the `talk` scene's path names. Ignored otherwise. */
  eventSlug?: string;
  /** The stage key the `talk` scene's path names. Ignored otherwise. */
  stageKey?: string;
}

/**
 * Build one cast scene's URL. Parameters are appended in a fixed order and
 * escaped with `encodeURIComponent`:
 *
 * - race scenes (quad, focus, metro): p1..p4, then focus (focus scene
 *   only), then c1 and c2 when named, then event when chosen, then cams
 *   always, then delay only when it is not 0.
 * - talk: c1, c2, cams. No seating and no delay: that scene has no runner
 *   holes, and no live feed to hold back (it re-reads the event every 30
 *   seconds, between races).
 */
export function buildCastUrl(
  origin: string,
  scene: CastSceneId,
  opts: CastUrlOpts,
): string {
  const path =
    scene === "talk"
      ? `/overlay/cast/event/${encodeURIComponent(opts.eventSlug ?? "")}/${encodeURIComponent(opts.stageKey ?? "")}/talk`
      : `/overlay/cast/race/${encodeURIComponent(opts.raceId ?? "")}/${scene}`;

  const params: string[] = [];

  if (scene !== "talk") {
    (opts.slots ?? []).slice(0, 4).forEach((name, i) => {
      if (name) params.push(`p${i + 1}=${encodeURIComponent(name)}`);
    });
    if (scene === "focus" && opts.focus) {
      params.push(`focus=${opts.focus}`);
    }
  }

  const [c1, c2] = opts.casters ?? [null, null];
  if (c1) params.push(`c1=${encodeURIComponent(c1)}`);
  if (c2) params.push(`c2=${encodeURIComponent(c2)}`);

  if (scene !== "talk" && opts.event) {
    params.push(`event=${encodeURIComponent(opts.event)}`);
  }

  params.push(`cams=${opts.cams}`);

  if (scene !== "talk" && opts.delayS) {
    params.push(`delay=${opts.delayS}`);
  }

  return `${origin}${path}${params.length ? `?${params.join("&")}` : ""}`;
}
