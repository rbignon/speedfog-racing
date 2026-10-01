/** Easter egg: race titles mentioning "frog" get the Speedfrog treatment. */
export function isFrogTitle(name: string): boolean {
  return name.toLowerCase().includes("frog");
}

/** Human-friendly label for race and solo statuses. */
export function statusLabel(s: string): string {
  switch (s) {
    case "setup":
      return "Upcoming";
    case "running":
      return "Live";
    case "finished":
      return "Finished";
    case "active":
      return "Active";
    case "abandoned":
      return "Abandoned";
    case "disqualified":
      return "Disqualified";
    case "cancelled":
      return "Cancelled";
    default:
      return s;
  }
}

/** Out of the race without a finish: abandoned or disqualified. */
export function isOutOfRace(status: string): boolean {
  return status === "abandoned" || status === "disqualified";
}
