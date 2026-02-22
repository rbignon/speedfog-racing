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
    default:
      return s;
  }
}
