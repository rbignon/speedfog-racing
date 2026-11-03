/** The rules of every run (races, Daily Seeds, ranked runs), one list for the
 * help page, the download window and the Speedrun rules (`SpeedrunRules.svelte`).
 * `lead` is the part the help page sets in bold; the text reads `lead + rest`. */
export interface RunRule {
  lead: string;
  rest: string;
}

export const RUN_RULES: RunRule[] = [
  { lead: "Glitchless", rest: "" },
  { lead: "Quit-outs allowed", rest: " (2-second penalty each)" },
  { lead: "No other mods", rest: ": only SpeedFog" },
  { lead: "Skips are allowed", rest: " within a zone" },
  {
    lead: "No sequence break",
    rest: ": reaching a zone other than through its fog gate is forbidden",
  },
  {
    lead: "LiveSplit allowed only without SoulSplitter",
    rest: ": SoulSplitter writes the game timer",
  },
];
