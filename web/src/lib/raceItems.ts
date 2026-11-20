export type RaceItemTier = "front" | "middle" | "back";

export interface RaceItemInfo {
  /** Base item key, also the icon file name under `/race_items/`. */
  key: string;
  name: string;
  effect: string;
  /** Ranks that can draw it, front to back. */
  tiers: RaceItemTier[];
}

/**
 * The race items as the latest seeds and server defaults have them: the names
 * and durations of the generator's catalog, the effects of the server's
 * `ITEM_RULES`, the tiers of its `DEFAULT_RACE_ITEMS_TIER_WEIGHTS`. Hand-kept:
 * update it with any of them.
 */
export const RACE_ITEMS: RaceItemInfo[] = [
  {
    key: "rune_pouch",
    name: "Rune Pouch",
    effect: "Grants runes, more of them later in the race.",
    tiers: ["front"],
  },
  {
    key: "banana",
    name: "Banana",
    effect: "Damages the runner just behind you. Never kills.",
    tiers: ["front"],
  },
  {
    key: "mushroom",
    name: "Mushroom",
    effect: "Infinite stamina for 30 s.",
    tiers: ["front", "middle"],
  },
  {
    key: "shield",
    name: "Shield",
    effect: "Held, not used: blocks the next item aimed at you.",
    tiers: ["middle"],
  },
  {
    key: "hammer",
    name: "Hammer",
    effect: "Everyone else fat-rolls for 15 s.",
    tiers: ["middle"],
  },
  {
    key: "ink",
    name: "Ink",
    effect: "Hides everyone else's exits on their overlay for 30 s.",
    tiers: ["middle"],
  },
  {
    key: "giant",
    name: "Giant",
    effect: "Everyone else grows huge for 15 s.",
    tiers: ["middle"],
  },
  {
    key: "red_shell",
    name: "Red Shell",
    effect: "Damages the runner just ahead of you, heavily. Never kills.",
    tiers: ["middle", "back"],
  },
  {
    key: "vanish",
    name: "Vanish",
    effect: "Everyone else's character turns invisible for 15 s.",
    tiers: ["middle", "back"],
  },
  {
    key: "slow_mo",
    name: "Slow-mo",
    effect: "Slows the runner just ahead of you for 15 s.",
    tiers: ["middle", "back"],
  },
  {
    key: "camera",
    name: "Camera",
    effect: "Messes with the camera of the runner just ahead of you for 15 s.",
    tiers: ["middle", "back"],
  },
  {
    key: "talisman_thief",
    name: "Talisman Thief",
    effect: "Steals a talisman from the runner just ahead of you, for good.",
    tiers: ["middle", "back"],
  },
  {
    key: "blue_shell",
    name: "Blue Shell",
    effect: "Halves the leader's max HP for 15 s, even if that is you.",
    tiers: ["back"],
  },
  {
    key: "lightning",
    name: "Lightning",
    effect: "Slows and shrinks everyone else for 15 s.",
    tiers: ["back"],
  },
  {
    key: "flask_stopper",
    name: "Flask Stopper",
    effect: "Blocks everyone else's flasks for 15 s.",
    tiers: ["back"],
  },
  {
    key: "toxic_blossom",
    name: "Toxic Blossom",
    effect: "Poisons everyone else.",
    tiers: ["back"],
  },
  {
    key: "star",
    name: "Star",
    effect: "Invincible for 15 s, and items aimed at you are blocked.",
    tiers: ["back"],
  },
  {
    key: "unseen_foes",
    name: "Unseen Foes",
    effect: "Hides everyone else's enemies for 15 s.",
    tiers: ["back"],
  },
  {
    key: "junk_weapon",
    name: "Junk Weapon",
    effect:
      "Forces a junk weapon into the right hand of the runner just ahead of you.",
    tiers: ["back"],
  },
  {
    key: "hunter",
    name: "Hunter",
    effect: "Sends Margit after the leader for 30 s, even if that is you.",
    tiers: ["back"],
  },
];

const TIER_PLACES: Record<RaceItemTier, string> = {
  front: "at the front",
  middle: "in the middle",
  back: "at the back",
};

/** Who can draw an item, as a sentence: "Drawn in the middle and at the back of the race." */
export function raceItemTierLine(tiers: RaceItemTier[]): string {
  const places = tiers.map((t) => TIER_PLACES[t]);
  const last = places.pop();
  if (last === undefined) return "";
  const list = places.length > 0 ? `${places.join(", ")} and ${last}` : last;
  return `Drawn ${list} of the race.`;
}
