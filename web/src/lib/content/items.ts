import type { ContentItem } from "./types";

export const CONTENT_ITEMS: ContentItem[] = [
  // ---------- Beginner tips ----------
  {
    id: "vigor-first",
    kind: "tip",
    level: "beginner",
    title: "Level Vigor first",
    short:
      "Put your first levels into **Vigor**. Enemy damage scales with route depth, and surviving a hit beats dealing one.",
  },
  {
    id: "godrick-great-rune",
    kind: "tip",
    level: "beginner",
    title: "Godrick's Great Rune",
    short:
      "**Godrick's Great Rune** raises every stat. Activate it with a Rune Arc, and you also **recover some HP and FP** every time you change zone.",
  },
  {
    id: "backtrack-freely",
    kind: "tip",
    level: "beginner",
    title: "Backtrack without guilt",
    short:
      "Fog gates are one-way, but you can always **fast travel back** to any grace. Revisiting an earlier zone to take another exit is often the fastest route.",
  },
  {
    id: "radahn-grace",
    kind: "tip",
    level: "beginner",
    title: "The Radahn grace",
    short:
      "After defeating **Radahn**, activate the **grace in his arena** before leaving, or you will not be able to progress to the next zone.",
  },
  {
    id: "overlay-exits",
    kind: "tip",
    level: "beginner",
    title: "Read the exit list",
    short:
      "The in-game overlay lists **every exit** of your current zone, with its destination once discovered. Check it before committing to a route.",
  },
  {
    id: "quit-outs",
    kind: "tip",
    level: "beginner",
    title: "Quit-outs are allowed",
    short:
      "**Quitting to the main menu** is legal. Use it to escape a bad fall or to reset a dangerous pull.",
  },
  {
    id: "spend-runes-early",
    kind: "tip",
    level: "beginner",
    title: "Spend runes early",
    short:
      "Levels are cheap at the start. **Spend your runes right after a boss** instead of carrying them into the next zone.",
  },

  // ---------- Advanced tips ----------
  {
    id: "tier-rescale",
    kind: "tip",
    level: "advanced",
    title: "Tier vs normal tier",
    short:
      "When the overlay shows '**tier X, normally Y**', the zone was rescaled: a large gap means enemies hit much harder or softer than that zone usually does.",
  },
  {
    id: "gap-splits",
    kind: "tip",
    level: "advanced",
    title: "Gaps are split-based",
    short:
      "The leaderboard gap compares you to the leader **at the same point of the route**, not in real time. A shrinking gap means you are actually gaining.",
  },
  {
    id: "hardcore-economy",
    kind: "tip",
    level: "advanced",
    pools: ["hardcore"],
    title: "Hardcore economy",
    short:
      "In Hardcore, weapons are **not upgraded for you**. Buy smithing stones at the Roundtable shop and commit to **one weapon** early.",
  },

  // ---------- Game changes: start ----------
  {
    id: "chapel-grace",
    kind: "game_change",
    category: "start",
    title: "Starting grace",
    short:
      "You start at the **Chapel of Anticipation** with a Site of Grace added right there, already active.",
    body: "Runs begin at the **Chapel of Anticipation**, where SpeedFog injects a **Site of Grace** that the base game does not have. It is pre-activated and usable for fast travel, and your respawn point is moved away from the Grafted Scion.",
  },
  {
    id: "roundtable-start",
    kind: "game_change",
    category: "start",
    title: "Roundtable Hold from the start",
    short:
      "The **Roundtable Hold** is unlocked from the start, and **Kale** has moved there.",
    body: "The **Roundtable Hold** is available from the first minute, without picking up the Wizened Finger. **Kale** the merchant has moved there, next to the **Twin Maiden Husks** shop.",
  },
  {
    id: "great-runes-restored",
    kind: "game_change",
    category: "start",
    title: "All Great Runes restored",
    short:
      "You start with **every Great Rune restored**. Activate one with a **Rune Arc** to get its buff immediately.",
  },
  {
    id: "care-package",
    kind: "game_change",
    category: "start",
    title: "Care package",
    short:
      "In most modes, every seed starts with a randomized **care package**: pre-upgraded weapons, armor, talismans, spells and tears, **identical for every racer**.",
  },
  {
    id: "starting-keys",
    kind: "game_change",
    category: "start",
    title: "Softlock keys granted",
    short:
      "**Key items** that would cause softlocks are granted at start: whetblades, the Academy Glintstone Key, the Spirit Calling Bell, talisman pouches, the lantern and more.",
  },
  {
    id: "merchants-relocated",
    kind: "game_change",
    category: "start",
    title: "Merchants relocated",
    short:
      "**Open-world merchants** are relocated inside zones. Keep an eye out, they can carry useful gear.",
  },

  // ---------- Game changes: traversal ----------
  {
    id: "one-way-fogs",
    kind: "game_change",
    category: "traversal",
    title: "One-way fog gates",
    short:
      "Fog gates only go **forward** and are rewired by the seed. To revisit a zone, **fast travel** to one of its graces.",
  },
  {
    id: "opened-gates",
    kind: "game_change",
    category: "traversal",
    title: "Pre-opened gates",
    short:
      "Barred gates that would block the route are **already open**, including the **Leyndell sewer grates** and a **Stormveil gate**.",
  },
  {
    id: "boss-return-portal",
    kind: "game_change",
    category: "traversal",
    title: "Return portals in arenas",
    short:
      "Boss arenas on the route have a **return portal**, and are exits to the next zone.",
  },
  //
  // ---------- Game changes: combat ----------
  {
    id: "torrent-arenas",
    kind: "game_change",
    category: "combat",
    title: "Torrent in boss arenas",
    short:
      "**Torrent** can be summoned in arenas where the base game forbids him: **Fia's Champions**, **Astel**, **Ancestor Spirit** and **Regal Ancestor Spirit**.",
  },
  {
    id: "boss-arena-lock",
    kind: "game_change",
    category: "combat",
    title: "Arenas lock behind you",
    short:
      "Entering a boss arena **locks its exits**. Once inside, the only way forward is through the boss.",
  },
  {
    id: "tier-scaling",
    kind: "game_change",
    category: "combat",
    title: "Depth-based scaling",
    short:
      "Enemies scale with the zone's **tier** (its depth in the route), not with their vanilla location.",
  },

  // ---------- Game changes: economy ----------
  {
    id: "roundtable-shop",
    kind: "game_change",
    category: "economy",
    title: "Roundtable smithing shop",
    short:
      "The **Twin Maiden Husks** sell **smithing stones**, and in some modes the **Sentry's Torch**.",
  },
  {
    id: "no-stat-requirements",
    kind: "game_change",
    category: "economy",
    title: "No stat requirements",
    short:
      "**Stat requirements on weapons are removed**: wield anything you find. Weapons found in the world are **auto-upgraded** to match your progression.",
  },
  {
    id: "all-recipes",
    kind: "game_change",
    category: "economy",
    title: "All recipes unlocked",
    short:
      "**Every crafting recipe** is unlocked from the start, and crafting materials are randomized into the world.",
  },

  // ---------- Game changes: QoL ----------
  {
    id: "rebirth-any-grace",
    kind: "game_change",
    category: "qol",
    title: "Rebirth anywhere",
    short:
      "**Rebirth** (respec) is available at **any Site of Grace** for a Larval Tear, not just at Rennala.",
  },
  {
    id: "fast-graces",
    kind: "game_change",
    category: "qol",
    title: "Faster graces",
    short:
      "Sitting at and discovering graces is **much faster** than in the base game.",
  },
  {
    id: "no-menu-delay",
    kind: "game_change",
    category: "qol",
    title: "No menu input delay",
    short: "The **input delay** when opening menus is removed.",
  },

  // ---------- Skips  ----------
  {
    id: "farum-dragon-template-lift-skip",
    kind: "skip",
    zoneId: "farumazula_lift",
    difficulty: 2,
    title: "Dragon Temple Lift",
    short: "Fast way to Godskin Duo gate",
    video: {
      youtubeId: "aKfimBgI4aI",
    },
  },
  {
    id: "academy-abducted-skip",
    kind: "skip",
    zoneId: "academy",
    difficulty: 1,
    title: "Academy abducted",
    short: "Easy skip to get abducted",
    video: {
      youtubeId: "MlN9gyDkOcM",
    },
  },
  {
    id: "unsightly-catacombs-skip",
    kind: "skip",
    zoneId: "altus_catacombs",
    difficulty: 2,
    title: "Unsightly catacombs skip",
    short: "Fast way to go to the lever",
    video: {
      youtubeId: "_qz1RvgUKM0",
    },
  },
  {
    id: "mohg-sewer-skip",
    kind: "skip",
    zoneId: "sewer",
    difficulty: 2,
    title: "Mohg Sewer Skip",
    short: "Skip to go to the elevator quickly",
    video: {
      youtubeId: "jxTcc9mZigE",
    },
  },
  {
    id: "academy-rooftops-skip",
    kind: "skip",
    zoneId: "academy_rooftops",
    difficulty: 3,
    title: "Academy Rooftops Redwolf Skip",
    short: "Going fast to Redwolf from Academy Rooftops",
    video: {
      youtubeId: "zGvn2ISu3M4",
    },
  },
  {
    id: "gaol-cave-lever-skip",
    kind: "skip",
    zoneId: "caelid_gaolcave",
    difficulty: 2,
    title: "Gaol Cave lever skip",
    short: "Fast access to the lever",
    video: {
      youtubeId: "lWW4ulJjl6c",
    },
  },
  {
    id: "darklight-skip",
    kind: "skip",
    zoneId: "scadualtus_catacombs",
    difficulty: 3,
    title: "Darklight Catacombs skip",
    short: "",
    video: {
      youtubeId: "oKFhWYJ-LNU",
    },
  },
  {
    id: "academy-front-skip",
    kind: "skip",
    zoneId: "academy_entrance",
    difficulty: 3,
    title: "Academy Front Gate Skip",
    short: "",
    video: {
      youtubeId: "to-Y_iEq5Ls",
    },
  },
  {
    id: "volcano-manor-cage-skip",
    kind: "skip",
    zoneId: "volcano_town",
    difficulty: 3,
    title: "Volcano Manor Cage Skip",
    short: "Cage Skip to Noble gate",
    video: {
      youtubeId: "LfSyv2nMo_E",
    },
  },
  {
    id: "castle-morne-skip",
    kind: "skip",
    zoneId: "peninsula_morne",
    difficulty: 2,
    title: "Castle Morne Skips",
    short: "Run through with skips",
    video: {
      youtubeId: "HQAIkDbeYDE",
    },
  },
  {
    id: "raya-tunnel-skip",
    kind: "skip",
    zoneId: "liurnia_tunnel",
    difficulty: 2,
    title: "Raya Crystal Tunnel Skip",
    short: "Skip to elevator",
    video: {
      youtubeId: "zhmEV-85ZRE",
    },
  },
  {
    id: "scorpion-catacombs-skip",
    kind: "skip",
    zoneId: "rauhbase_catacombs",
    difficulty: 2,
    title: "Scorpion River Catacombs Skip",
    short: "Skip the first part",
    video: {
      youtubeId: "Ge8Uyuc9naE",
    },
  },
  {
    id: "leyndell-skip",
    kind: "skip",
    zoneId: "leyndell",
    difficulty: 3,
    title: "Leyndell Skip",
    short: "3 versions of the skip, from fastest to easier",
    video: {
      youtubeId: "U1RWdWrnTjY",
    },
  },
  {
    id: "sage-cave-skip",
    kind: "skip",
    zoneId: "altus_sagescave",
    difficulty: 5,
    title: "Sage's Cave Skip",
    short: "Hard",
    video: {
      youtubeId: "O7bslEj-vFs",
    },
  },
  {
    id: "specimen-storehouse-skip",
    kind: "skip",
    zoneId: "storehouse",
    difficulty: 4,
    title: "Hand skip",
    short: "",
    video: {
      youtubeId: "ZoEMvNgeJQM",
    },
  },
  {
    id: "rauh-east-tree-skip",
    kind: "skip",
    zoneId: "rauhruins_east",
    difficulty: 3,
    title: "Tree skip",
    short: "",
    video: {
      youtubeId: "MFN0z5d_ahg",
    },
  },
  {
    id: "farum-bird-skip",
    kind: "skip",
    zoneId: "farumazula",
    difficulty: 4,
    title: "Bird skip",
    short: "",
    video: {
      youtubeId: "GwJm_vCvgls",
    },
  },
  {
    id: "sellia-tunnel-skip",
    kind: "skip",
    zoneId: "caelid_selliatunnel",
    difficulty: 2,
    title: "Sellia Crystal Tunnel skip",
    short: "",
    video: {
      youtubeId: "yAckrwdV7SE",
    },
  },
  {
    id: "dragon-pit-skip",
    kind: "skip",
    zoneId: "gravesite_dragonpit",
    difficulty: 2,
    title: "Dragon's Pit skip",
    short: "",
    video: {
      youtubeId: "O6iINXP1ccU",
    },
  },
  {
    id: "nokron-skip",
    kind: "skip",
    zoneId: "siofra_nokron",
    difficulty: 3,
    title: "Skip to teleporter",
    short:
      "Nokron skip down to get the teleporter beside Fingerslayer Blade faster",
    video: {
      youtubeId: "yTWtl8rOpxY",
    },
  },
  {
    id: "shaded-castle-skip",
    kind: "skip",
    zoneId: "altus_shaded",
    difficulty: 2,
    title: "Backwards Fast Route",
    short: "",
    video: {
      youtubeId: "BkxpWreZKxY",
    },
  },
];
